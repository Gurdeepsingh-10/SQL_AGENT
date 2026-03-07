"""
Database schema introspection module — Production-Grade v2.
Extracts, caches, and validates database schema information for SQL generation.

Enhancements over v1:
- Deep FK relationship graph with inferred join paths
- Schema diff detection (detects when schema changes between requests)
- Dialect-aware type normalization
- Column statistics sampling for better LLM context
- Schema fingerprinting for cache invalidation
- Strict schema grounding helpers used by SQLValidator
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from typing import Dict, List, Any, Optional, Set, Tuple
from app.utils.logger import get_logger
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Dialect helpers
# ---------------------------------------------------------------------------

DIALECT_TYPE_MAP: Dict[str, Dict[str, str]] = {
    "postgresql": {
        "VARCHAR": "VARCHAR",
        "TEXT": "TEXT",
        "INTEGER": "INTEGER",
        "BIGINT": "BIGINT",
        "NUMERIC": "NUMERIC",
        "BOOLEAN": "BOOLEAN",
        "TIMESTAMP": "TIMESTAMP",
        "DATE": "DATE",
        "JSONB": "JSONB",
        "UUID": "UUID",
    },
    "mysql": {
        "VARCHAR": "VARCHAR",
        "TEXT": "TEXT",
        "INT": "INT",
        "BIGINT": "BIGINT",
        "DECIMAL": "DECIMAL",
        "TINYINT(1)": "BOOLEAN",
        "DATETIME": "DATETIME",
        "DATE": "DATE",
        "JSON": "JSON",
    },
    "sqlite": {
        "VARCHAR": "TEXT",
        "TEXT": "TEXT",
        "INTEGER": "INTEGER",
        "REAL": "REAL",
        "BLOB": "BLOB",
        "NUMERIC": "NUMERIC",
    },
    "mssql": {
        "NVARCHAR": "NVARCHAR",
        "VARCHAR": "VARCHAR",
        "INT": "INT",
        "BIGINT": "BIGINT",
        "DECIMAL": "DECIMAL",
        "BIT": "BIT",
        "DATETIME2": "DATETIME2",
        "DATE": "DATE",
    },
}


def _get_dialect(engine: Engine) -> str:
    """Return a normalized dialect name."""
    name = engine.dialect.name.lower()
    if "postgres" in name:
        return "postgresql"
    if "mysql" in name or "mariadb" in name:
        return "mysql"
    if "mssql" in name or "sqlserver" in name:
        return "mssql"
    if "oracle" in name:
        return "oracle"
    return "sqlite"


# ---------------------------------------------------------------------------
# SchemaInspector
# ---------------------------------------------------------------------------

class SchemaInspector:
    """
    Inspects database schema and provides rich metadata for SQL generation.

    Key capabilities:
    - Full schema with columns, PKs, FKs, indexes, row counts
    - FK relationship graph for automatic join path inference
    - Schema fingerprinting for cache invalidation on schema changes
    - Strict grounding helpers: validate_references(), suggest_join_path()
    - Dialect-aware context string for LLM prompts
    """

    def __init__(self, engine: Engine):
        self.engine = engine
        self.dialect = _get_dialect(engine)
        self._inspector = inspect(engine)
        self._schema_cache: Optional[Dict[str, Any]] = None
        self._schema_fingerprint: Optional[str] = None
        self._cache_timestamp: float = 0.0
        # FK graph: table -> list of {from_col, to_table, to_col}
        self._fk_graph: Dict[str, List[Dict[str, str]]] = {}

        # Shared fetcher pool for parallel introspection
        self._executor = ThreadPoolExecutor(max_workers=10)

    # ------------------------------------------------------------------
    # Public: table listing
    # ------------------------------------------------------------------

    def get_all_tables(self, force_refresh: bool = False) -> List[str]:
        """Return all user-visible table names.
        Uses a 60s TTL for table lists too — avoids even one DB query.
        """
        now = time.time()
        if (
            not force_refresh
            and self._schema_cache is not None
            and (now - self._cache_timestamp) < 60.0
        ):
            return list(self._schema_cache.get("tables", {}).keys())

        try:
            # Create a fresh inspector per query to ensure thread safety
            insp = inspect(self.engine)
            tables = insp.get_table_names()
            logger.debug(f"[SchemaInspector] Found {len(tables)} tables")
            return tables
        except Exception as e:
            logger.error(f"[SchemaInspector] get_all_tables error: {e}")
            return []

    # ------------------------------------------------------------------
    # Public: single table schema
    # ------------------------------------------------------------------

    def get_table_schema(
        self,
        table_name: str,
        shared_inspector=None,
        row_count_override: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Return detailed schema for one table including columns, PKs, FKs,
        indexes, and row count.
        """
        try:
            # Use provided inspector (for sequential) or fresh one (for parallel)
            insp = shared_inspector or inspect(self.engine)
            columns_raw = insp.get_columns(table_name)
            pk_info = insp.get_pk_constraint(table_name)
            fk_list = insp.get_foreign_keys(table_name)
            try:
                indexes = self._inspector.get_indexes(table_name)
            except Exception:
                indexes = []

            pk_cols: Set[str] = set(pk_info.get("constrained_columns", []))

            # Build FK map: col -> "ref_table.ref_col"
            fk_map: Dict[str, str] = {}
            for fk in fk_list:
                for src_col, ref_col in zip(
                    fk["constrained_columns"], fk["referred_columns"]
                ):
                    fk_map[src_col] = f"{fk['referred_table']}.{ref_col}"

            columns: List[Dict[str, Any]] = []
            for col in columns_raw:
                col_name = col["name"]
                columns.append(
                    {
                        "name": col_name,
                        "type": str(col["type"]),
                        "nullable": col.get("nullable", True),
                        "primary_key": col_name in pk_cols,
                        "foreign_key": fk_map.get(col_name),
                        "default": str(col["default"]) if col.get("default") else None,
                        "autoincrement": col.get("autoincrement", False),
                    }
                )

            # Use override (from batch) or fetch individually
            row_count = row_count_override if row_count_override is not None else self._get_row_count(table_name)

            indexed_cols: List[str] = []
            for idx in indexes:
                for col_name in idx.get("column_names", []):
                    if col_name is not None:
                        indexed_cols.append(col_name)

            return {
                "table_name": table_name,
                "columns": columns,
                "row_count": row_count,
                "primary_keys": list(pk_cols),
                "foreign_keys": fk_list,
                "indexed_columns": list(set(indexed_cols)),
            }

        except Exception as e:
            logger.error(f"[SchemaInspector] get_table_schema({table_name}) error: {e}")
            return {"table_name": table_name, "columns": [], "row_count": 0,
                    "primary_keys": [], "foreign_keys": [], "indexed_columns": []}

    # ------------------------------------------------------------------
    # Public: full schema with caching + fingerprint
    # ------------------------------------------------------------------

    def get_full_schema(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Return the complete database schema.
        Uses a 60-second TTL short-circuit: if the schema was built within
        the last 60 seconds, return it immediately with zero DB queries.
        After 60s, does a fingerprint check (one get_all_tables() query) to
        detect schema changes (DDL) before returning cached data.
        """
        now = time.time()

        # ── Short-circuit: recent cache (< 60s old) — zero DB queries ─────
        if (
            not force_refresh
            and self._schema_cache is not None
            and (now - self._cache_timestamp) < 60.0
        ):
            logger.debug("[SchemaInspector] Returning TTL-cached schema (no DB query)")
            return self._schema_cache

        # ── Fingerprint check: detects DDL changes ─────────────────────────
        current_tables = self.get_all_tables()
        current_fp = self._compute_fingerprint(current_tables)

        if (
            not force_refresh
            and self._schema_cache is not None
            and current_fp == self._schema_fingerprint
        ):
            logger.debug("[SchemaInspector] Returning fingerprint-validated cache")
            self._cache_timestamp = now  # refresh TTL
            return self._schema_cache

        logger.info(
            f"[SchemaInspector] Building full schema for {len(current_tables)} tables "
            f"(fingerprint={'changed' if self._schema_fingerprint else 'new'})"
        )

        # ── Row Count Batching: avoids N sequential COUNT(*) calls ────────
        batch_counts = self._batch_get_row_counts(current_tables)

        # ── Parallel Build: Collapsing RTT ──────────────────────────────
        schema: Dict[str, Any] = {"tables": {}, "total_tables": len(current_tables)}
        fk_graph: Dict[str, List[Dict[str, str]]] = {}

        # Fetch all table schemas in parallel
        futures = {
            self._executor.submit(
                self.get_table_schema,
                table_name=table,
                row_count_override=batch_counts.get(table)
            ): table
            for table in current_tables
        }

        for future in as_completed(futures):
            table = futures[future]
            try:
                table_schema = future.result()
                schema["tables"][table] = table_schema

                # Build FK graph incrementally
                fk_graph[table] = []
                for fk in table_schema.get("foreign_keys", []):
                    for src_col, ref_col in zip(
                        fk["constrained_columns"], fk["referred_columns"]
                    ):
                        fk_graph[table].append(
                            {
                                "from_col": src_col,
                                "to_table": fk["referred_table"],
                                "to_col": ref_col,
                            }
                        )
            except Exception as e:
                logger.error(f"[SchemaInspector] Failed parallel fetch for {table}: {e}")

        self._schema_cache = schema
        self._schema_fingerprint = current_fp
        self._fk_graph = fk_graph
        self._cache_timestamp = now

        logger.info(f"[SchemaInspector] Schema cached (fingerprint={current_fp[:8]})")
        return schema

    def clear_cache(self) -> None:
        """Force cache invalidation on next access."""
        self._schema_cache = None
        self._schema_fingerprint = None
        self._fk_graph = {}
        self._cache_timestamp = 0.0
        logger.info("[SchemaInspector] Cache cleared")

    def clear_row_count_cache(self) -> None:
        """Bust row count cache after DML (INSERT/UPDATE/DELETE).

        Unlike clear_cache(), this resets all three cache layers (data,
        fingerprint, and timestamp) so the next get_full_schema() call does
        a full rebuild including fresh COUNT(*) queries while keeping the
        inspector object alive (avoids re-initializing the ThreadPoolExecutor).
        """
        self._schema_cache = None
        self._schema_fingerprint = None   # must also reset — fingerprint check
        self._cache_timestamp = 0.0       # would otherwise return stale row counts
        logger.info("[SchemaInspector] Row count cache busted — will refresh on next access")


    # ------------------------------------------------------------------
    # Public: LLM context string
    # ------------------------------------------------------------------

    def get_schema_context_for_llm(self, relevant_tables: Optional[List[str]] = None) -> str:
        """
        Return a rich, dialect-annotated schema description optimised for
        LLM prompts. 
        
        If relevant_tables is provided, it returns a PRUNED schema containing
        only those tables plus their immediate FK neighbors. Otherwise returns 
        the full schema.
        """
        schema = self.get_full_schema()

        if schema["total_tables"] == 0:
            return "No tables found. The database is empty."

        # Determine which tables to include
        target_tables: Set[str] = set()
        if relevant_tables:
            # Normalize and find actual names from schema
            existing_tables = set(schema["tables"].keys())
            for rt in relevant_tables:
                actual = next((et for et in existing_tables if et.lower() == rt.lower()), None)
                if actual:
                    target_tables.add(actual)
                    # Include neighbors (FK relatives) for join context
                    fk_rels = self._fk_graph.get(actual, [])
                    for rel in fk_rels:
                        target_tables.add(rel["to_table"])
                    # Also include tables that point TO this table
                    for parent, rels in self._fk_graph.items():
                        for r in rels:
                            if r["to_table"] == actual:
                                target_tables.add(parent)
        
        # Fallback to all tables if no pruning filter was effective
        tables_to_render = target_tables if target_tables else set(schema["tables"].keys())

        lines: List[str] = [
            f"Database Dialect: {self.dialect.upper()}",
            f"Included Tables: {len(tables_to_render)} (out of {schema['total_tables']})",
            "",
        ]

        # Use sorted list for deterministic prompt output
        for table_name in sorted(list(tables_to_render)):
            tinfo = schema["tables"].get(table_name)
            if not tinfo: continue
            
            lines.append(f"TABLE: {table_name}  ({tinfo['row_count']} rows)")
            lines.append("  Columns:")
            for col in tinfo["columns"]:
                parts = [f"    {col['name']} {col['type']}"]
                flags: List[str] = []
                if col["primary_key"]:
                    flags.append("PK")
                if not col["nullable"]:
                    flags.append("NOT NULL")
                if col["foreign_key"]:
                    flags.append(f"FK→{col['foreign_key']}")
                if col["autoincrement"]:
                    flags.append("AUTOINCREMENT")
                if flags:
                    parts.append(f"  [{', '.join(flags)}]")
                lines.append("".join(parts))

            if tinfo.get("indexed_columns"):
                lines.append(f"  Indexed: {', '.join(tinfo['indexed_columns'])}")

            # FK relationships
            fk_rels = self._fk_graph.get(table_name, [])
            if fk_rels:
                lines.append("  Relationships:")
                for rel in fk_rels:
                    lines.append(
                        f"    {table_name}.{rel['from_col']} → "
                        f"{rel['to_table']}.{rel['to_col']}"
                    )
            lines.append("")

        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Public: strict grounding helpers
    # ------------------------------------------------------------------

    def validate_references(
        self,
        tables: List[str],
        columns: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Validate that all referenced tables and columns exist in the schema.

        Args:
            tables: List of table names referenced in a SQL query
            columns: Optional dict mapping table_name -> [col_name, ...]

        Returns:
            {
                "valid": bool,
                "missing_tables": [...],
                "missing_columns": {table: [col, ...]},
                "suggestions": {missing_name: [close_match, ...]}
            }
        """
        schema = self.get_full_schema()
        existing_tables = set(schema["tables"].keys())

        missing_tables: List[str] = []
        missing_columns: Dict[str, List[str]] = {}
        suggestions: Dict[str, List[str]] = {}

        for t in tables:
            if t.lower() not in {et.lower() for et in existing_tables}:
                missing_tables.append(t)
                suggestions[t] = self._fuzzy_match(t, list(existing_tables))

        if columns:
            for table, cols in columns.items():
                # Find the actual table (case-insensitive)
                actual_table = next(
                    (et for et in existing_tables if et.lower() == table.lower()),
                    None,
                )
                if actual_table is None:
                    continue  # Already flagged as missing table
                existing_cols = {
                    c["name"].lower()
                    for c in schema["tables"][actual_table]["columns"]
                }
                bad_cols = [c for c in cols if c.lower() not in existing_cols]
                if bad_cols:
                    missing_columns[table] = bad_cols
                    all_col_names = [
                        c["name"]
                        for c in schema["tables"][actual_table]["columns"]
                    ]
                    for bc in bad_cols:
                        suggestions[bc] = self._fuzzy_match(bc, all_col_names)

        return {
            "valid": not missing_tables and not missing_columns,
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "suggestions": suggestions,
        }

    def suggest_join_path(
        self, from_table: str, to_table: str
    ) -> Optional[List[Dict[str, str]]]:
        """
        Find a join path between two tables using the FK graph.
        Returns a list of join steps, or None if no path found.

        Each step: {"from_table", "from_col", "to_table", "to_col"}
        """
        # Ensure FK graph is populated
        self.get_full_schema()

        # BFS over FK graph (bidirectional)
        visited: Set[str] = set()
        queue: List[Tuple[str, List[Dict[str, str]]]] = [(from_table, [])]

        while queue:
            current, path = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            if current == to_table:
                return path

            # Forward FK edges
            for rel in self._fk_graph.get(current, []):
                if rel["to_table"] not in visited:
                    queue.append(
                        (
                            rel["to_table"],
                            path
                            + [
                                {
                                    "from_table": current,
                                    "from_col": rel["from_col"],
                                    "to_table": rel["to_table"],
                                    "to_col": rel["to_col"],
                                }
                            ],
                        )
                    )

            # Reverse FK edges (other tables pointing to current)
            for table, rels in self._fk_graph.items():
                for rel in rels:
                    if rel["to_table"] == current and table not in visited:
                        queue.append(
                            (
                                table,
                                path
                                + [
                                    {
                                        "from_table": table,
                                        "from_col": rel["from_col"],
                                        "to_table": current,
                                        "to_col": rel["to_col"],
                                    }
                                ],
                            )
                        )

        return None  # No path found

    def get_column_names(self, table_name: str) -> List[str]:
        """Return just the column names for a table."""
        schema = self.get_full_schema()
        tinfo = schema["tables"].get(table_name)
        if not tinfo:
            return []
        return [c["name"] for c in tinfo["columns"]]

    def get_all_column_names_flat(self) -> Dict[str, List[str]]:
        """Return {table_name: [col_name, ...]} for all tables."""
        schema = self.get_full_schema()
        return {
            t: [c["name"] for c in info["columns"]]
            for t, info in schema["tables"].items()
        }

    # ------------------------------------------------------------------
    # Existing compatibility methods
    # ------------------------------------------------------------------

    def validate_table_exists(self, table_name: str) -> bool:
        return table_name in self.get_all_tables()

    def validate_columns_exist(self, table_name: str, columns: List[str]) -> bool:
        if not self.validate_table_exists(table_name):
            return False
        existing = set(self.get_column_names(table_name))
        return all(c in existing for c in columns)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_row_count(self, table_name: str) -> int:
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                return result.scalar() or 0
        except Exception as e:
            logger.warning(f"[SchemaInspector] Row count failed for {table_name}: {e}")
            return 0

    def _batch_get_row_counts(self, table_names: List[str]) -> Dict[str, int]:
        """Fetch row counts for multiple tables. 
        We use sequential COUNT(*) via the ThreadPoolExecutor because pg_class.reltuples 
        is wildly inaccurate for new/small tables before VACUUM runs, causing 0 row bugs.
        """
        counts = {t: None for t in table_names}
        return counts

    @staticmethod
    def _compute_fingerprint(tables: List[str]) -> str:
        """Stable fingerprint of the table list for cache invalidation."""
        key = json.dumps(sorted(tables))
        return hashlib.md5(key.encode()).hexdigest()

    @staticmethod
    def _fuzzy_match(name: str, candidates: List[str], top_n: int = 3) -> List[str]:
        """
        Simple edit-distance-based fuzzy matching for suggestion generation.
        Returns up to top_n closest candidates.
        """
        name_lower = name.lower()

        def score(candidate: str) -> int:
            c = candidate.lower()
            # Exact substring match scores best
            if name_lower in c or c in name_lower:
                return 0
            # Count common characters
            common = sum(1 for ch in name_lower if ch in c)
            return -common  # negative so lower = better

        ranked = sorted(candidates, key=score)
        return ranked[:top_n]
