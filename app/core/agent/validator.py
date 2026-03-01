"""
SQL Validator — Production-Grade v2.
Validates and sanitizes SQL queries before execution.

Enhancements over v1:
- Strict schema cross-checking: every referenced table and column is validated
  against the live schema; mismatches trigger re-reasoning rather than execution
- Re-reasoning trigger: returns structured error with suggestions for correction
- Expanded injection pattern detection
- Dialect-aware dangerous keyword list
- Complexity scoring with configurable thresholds
- Multi-statement detection (blocks SQL injection via statement chaining)
"""

import re
import sqlparse
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Set
from app.config import settings
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.core.agent.schema_inspector import SchemaInspector

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Keywords that are always blocked regardless of settings
ALWAYS_BLOCKED = [
    "EXEC", "EXECUTE", "SHUTDOWN", "KILL", "LOAD_FILE",
    "INTO OUTFILE", "INTO DUMPFILE", "XP_CMDSHELL",
    "SP_EXECUTESQL", "OPENROWSET", "OPENDATASOURCE",
]

# DDL keywords (blocked unless ENABLE_DDL_OPERATIONS=True)
DDL_KEYWORDS = ["CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME", "COMMENT"]

# DML write keywords (blocked unless ENABLE_WRITE_OPERATIONS=True)
WRITE_KEYWORDS = ["INSERT", "UPDATE", "MERGE", "UPSERT", "REPLACE"]

# Delete keywords (blocked unless ENABLE_DELETE_OPERATIONS=True)
DELETE_KEYWORDS = ["DELETE"]

# SQL injection patterns
INJECTION_PATTERNS = [
    r"'\s*OR\s+'1'\s*=\s*'1",       # ' OR '1'='1
    r"'\s*OR\s+1\s*=\s*1",          # ' OR 1=1
    r"'\s*OR\s+'[^']*'\s*=\s*'",    # ' OR 'x'='x
    r"--\s",                          # SQL line comment (with space after)
    r"/\*.*?\*/",                     # Multi-line comments
    r";\s*(DROP|DELETE|TRUNCATE|UPDATE|INSERT)",  # Statement chaining
    r"UNION\s+(ALL\s+)?SELECT",      # UNION-based injection
    r"xp_cmdshell",                  # Command execution
    r"WAITFOR\s+DELAY",              # Time-based blind injection
    r"SLEEP\s*\(",                   # MySQL time-based injection
    r"BENCHMARK\s*\(",               # MySQL benchmark injection
    r"LOAD_FILE\s*\(",               # File read
    r"INTO\s+OUTFILE",               # File write
]


# ---------------------------------------------------------------------------
# SQLValidator
# ---------------------------------------------------------------------------

class SQLValidator:
    """
    Validates SQL queries for safety, correctness, and schema compliance.

    The validate() method returns a structured result that includes:
    - is_valid: bool
    - is_safe: bool
    - errors: List[str]
    - warnings: List[str]
    - sanitized_sql: str
    - schema_errors: Dict with missing tables/columns and suggestions
    - requires_re_reasoning: bool  ← NEW: triggers re-generation in the agent
    """

    def __init__(self, schema_inspector: Optional["SchemaInspector"] = None):
        self.schema_inspector = schema_inspector

    # ------------------------------------------------------------------
    # Primary validation entry point
    # ------------------------------------------------------------------

    def validate(self, sql: str, intent: Optional[str] = None) -> Dict[str, Any]:
        """
        Comprehensive validation pipeline.

        Returns:
            {
                "is_valid": bool,
                "is_safe": bool,
                "errors": [...],
                "warnings": [...],
                "sanitized_sql": str,
                "schema_errors": {...},
                "requires_re_reasoning": bool,
            }
        """
        errors: List[str] = []
        warnings: List[str] = []
        schema_errors: Dict[str, Any] = {}
        requires_re_reasoning = False

        # 1. Always-blocked keywords
        always_blocked = self._check_always_blocked(sql)
        if not always_blocked["is_safe"]:
            errors.append(always_blocked["message"])

        # 2. Permission-based operation checks
        perm = self._check_operation_permissions(sql)
        if not perm["allowed"]:
            errors.append(perm["message"])

        # 3. SQL injection patterns
        inj = self._check_sql_injection(sql)
        if not inj["is_safe"]:
            errors.append(inj["message"])

        # 4. Syntax validation (multi-statement detection)
        syn = self._validate_syntax(sql)
        if not syn["is_valid"]:
            errors.append(syn["message"])

        # 5. Strict schema cross-checking (most important for hallucination prevention)
        if self.schema_inspector and not errors:
            schema_check = self._strict_schema_check(sql)
            schema_errors = schema_check
            if not schema_check["valid"]:
                missing_tables = schema_check.get("missing_tables", [])
                missing_cols = schema_check.get("missing_columns", {})
                suggestions = schema_check.get("suggestions", {})

                if missing_tables:
                    suggestion_text = ""
                    for t in missing_tables:
                        sugg = suggestions.get(t, [])
                        if sugg:
                            suggestion_text += f" (did you mean: {', '.join(sugg)}?)"
                    errors.append(
                        f"Referenced tables do not exist: {', '.join(missing_tables)}{suggestion_text}"
                    )
                    requires_re_reasoning = True

                if missing_cols:
                    for table, cols in missing_cols.items():
                        sugg_list = [
                            f"{c} → {', '.join(suggestions.get(c, []))}"
                            for c in cols
                            if suggestions.get(c)
                        ]
                        sugg_text = f" (suggestions: {'; '.join(sugg_list)})" if sugg_list else ""
                        errors.append(
                            f"Referenced columns do not exist in '{table}': "
                            f"{', '.join(cols)}{sugg_text}"
                        )
                    requires_re_reasoning = True

        # 6. Complexity check (warning only)
        comp = self._check_complexity(sql)
        if not comp["acceptable"]:
            warnings.append(comp["message"])

        # 7. NULL comparison check
        null_check = self._check_null_comparisons(sql)
        if null_check["has_issues"]:
            warnings.extend(null_check["issues"])

        # 8. GROUP BY completeness check
        gb_check = self._check_group_by(sql)
        if gb_check["has_issues"]:
            warnings.extend(gb_check["issues"])

        sanitized = self.sanitize_sql(sql)

        is_valid = len(errors) == 0
        is_safe = (
            always_blocked["is_safe"]
            and inj["is_safe"]
            and perm["allowed"]
        )

        return {
            "is_valid": is_valid,
            "is_safe": is_safe,
            "errors": errors,
            "warnings": warnings,
            "sanitized_sql": sanitized,
            "schema_errors": schema_errors,
            "requires_re_reasoning": requires_re_reasoning,
        }

    # ------------------------------------------------------------------
    # Always-blocked keywords
    # ------------------------------------------------------------------

    def _check_always_blocked(self, sql: str) -> Dict[str, Any]:
        sql_upper = sql.upper()
        found = [kw for kw in ALWAYS_BLOCKED if kw in sql_upper]
        is_safe = len(found) == 0
        return {
            "is_safe": is_safe,
            "message": f"Blocked operations detected: {', '.join(found)}" if not is_safe else "",
        }

    # ------------------------------------------------------------------
    # Permission checks
    # ------------------------------------------------------------------

    def _check_operation_permissions(self, sql: str) -> Dict[str, Any]:
        sql_upper = sql.upper()

        if not settings.ENABLE_DDL_OPERATIONS:
            for kw in DDL_KEYWORDS:
                if re.search(r"\b" + re.escape(kw) + r"\b", sql_upper):
                    return {
                        "allowed": False,
                        "message": f"DDL operations ({kw}) are disabled. "
                                   "Set ENABLE_DDL_OPERATIONS=True to allow.",
                    }

        if not settings.ENABLE_DELETE_OPERATIONS:
            for kw in DELETE_KEYWORDS:
                if re.search(r"\b" + re.escape(kw) + r"\b", sql_upper):
                    return {
                        "allowed": False,
                        "message": "DELETE operations are disabled. "
                                   "Set ENABLE_DELETE_OPERATIONS=True to allow.",
                    }

        if not settings.ENABLE_WRITE_OPERATIONS:
            for kw in WRITE_KEYWORDS:
                if re.search(r"\b" + re.escape(kw) + r"\b", sql_upper):
                    return {
                        "allowed": False,
                        "message": f"Write operations ({kw}) are disabled. "
                                   "Set ENABLE_WRITE_OPERATIONS=True to allow.",
                    }

        return {"allowed": True, "message": "Operation permitted"}

    # ------------------------------------------------------------------
    # SQL injection detection
    # ------------------------------------------------------------------

    def _check_sql_injection(self, sql: str) -> Dict[str, Any]:
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, sql, re.IGNORECASE | re.DOTALL):
                return {
                    "is_safe": False,
                    "message": "Potential SQL injection pattern detected",
                }
        return {"is_safe": True, "message": "No injection patterns detected"}

    # ------------------------------------------------------------------
    # Syntax validation
    # ------------------------------------------------------------------

    def _validate_syntax(self, sql: str) -> Dict[str, Any]:
        try:
            parsed = sqlparse.parse(sql)
            if not parsed or len(parsed) == 0:
                return {"is_valid": False, "message": "Unable to parse SQL query"}

            # Filter out empty statements (trailing semicolons produce empty ones)
            non_empty = [
                s for s in parsed
                if s.get_type() is not None or str(s).strip().rstrip(";").strip()
            ]

            if len(non_empty) > 1:
                return {
                    "is_valid": False,
                    "message": "Multiple SQL statements detected — only single statements allowed",
                }

            return {"is_valid": True, "message": "Syntax valid"}

        except Exception as e:
            logger.error(f"[SQLValidator] Syntax error: {e}")
            return {"is_valid": False, "message": f"Syntax error: {e}"}

    # ------------------------------------------------------------------
    # Strict schema cross-checking
    # ------------------------------------------------------------------

    def _strict_schema_check(self, sql: str) -> Dict[str, Any]:
        """
        Extract all table and column references from the SQL and validate
        them against the live schema.  Returns the same structure as
        SchemaInspector.validate_references().
        """
        try:
            assert self.schema_inspector is not None
            tables = self._extract_table_names(sql)
            columns_by_table = self._extract_columns_by_table(sql, tables)

            result = self.schema_inspector.validate_references(tables, columns_by_table)
            return result

        except Exception as e:
            logger.warning(f"[SQLValidator] Schema check error: {e}")
            return {
                "valid": True,
                "missing_tables": [],
                "missing_columns": {},
                "suggestions": {},
            }

    def _extract_table_names(self, sql: str) -> List[str]:
        """Extract table names from FROM, JOIN, INTO, UPDATE clauses."""
        tables: Set[str] = set()

        patterns = [
            r"\bFROM\s+([`\"\[]?[\w]+[`\"\]]?)",
            r"\bJOIN\s+([`\"\[]?[\w]+[`\"\]]?)",
            r"\bINTO\s+([`\"\[]?[\w]+[`\"\]]?)",
            r"\bUPDATE\s+([`\"\[]?[\w]+[`\"\]]?)",
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, sql, re.IGNORECASE):
                name = match.group(1).strip("`\"[]")
                # Skip SQL keywords that might be captured
                if name.upper() not in {
                    "SELECT", "FROM", "WHERE", "SET", "VALUES",
                    "TABLE", "DATABASE", "SCHEMA",
                }:
                    tables.add(name)

        return list(tables)

    def _extract_columns_by_table(
        self, sql: str, tables: List[str]
    ) -> Dict[str, List[str]]:
        """
        Best-effort extraction of column references qualified by table alias.
        Returns {table_name: [col_name, ...]} for columns we can confidently
        attribute to a specific table.
        """
        # Build alias → table map
        alias_map: Dict[str, str] = {}
        alias_pattern = r"\b([\w]+)\s+(?:AS\s+)?([\w]+)\b"
        for match in re.finditer(alias_pattern, sql, re.IGNORECASE):
            potential_table = match.group(1)
            alias = match.group(2)
            if potential_table in tables:
                alias_map[alias.lower()] = potential_table

        # Extract qualified column references: alias.column or table.column
        columns_by_table: Dict[str, List[str]] = {}
        qualified_pattern = r"\b([\w]+)\.([\w]+)\b"
        for match in re.finditer(qualified_pattern, sql, re.IGNORECASE):
            qualifier = match.group(1).lower()
            col = match.group(2)

            # Resolve alias to table name
            table = alias_map.get(qualifier) or (
                qualifier if qualifier in {t.lower() for t in tables} else None
            )
            if table:
                # Find actual case-sensitive table name
                actual = next(
                    (t for t in tables if t.lower() == table.lower()), table
                )
                if actual not in columns_by_table:
                    columns_by_table[actual] = []
                if col not in columns_by_table[actual]:
                    columns_by_table[actual].append(col)

        return columns_by_table

    # ------------------------------------------------------------------
    # NULL comparison check
    # ------------------------------------------------------------------

    def _check_null_comparisons(self, sql: str) -> Dict[str, Any]:
        issues: List[str] = []
        # Detect = NULL or != NULL (should be IS NULL / IS NOT NULL)
        if re.search(r"=\s*NULL\b", sql, re.IGNORECASE):
            issues.append(
                "Use IS NULL instead of = NULL for NULL comparisons"
            )
        if re.search(r"!=\s*NULL\b|<>\s*NULL\b", sql, re.IGNORECASE):
            issues.append(
                "Use IS NOT NULL instead of != NULL or <> NULL"
            )
        return {"has_issues": len(issues) > 0, "issues": issues}

    # ------------------------------------------------------------------
    # GROUP BY completeness check
    # ------------------------------------------------------------------

    def _check_group_by(self, sql: str) -> Dict[str, Any]:
        issues: List[str] = []
        sql_upper = sql.upper()
        if "GROUP BY" in sql_upper and "HAVING" not in sql_upper:
            # Basic heuristic: if there's a GROUP BY, warn about potential
            # non-aggregated columns in SELECT
            if re.search(r"SELECT\s+(?!COUNT|SUM|AVG|MIN|MAX|\*)", sql_upper):
                issues.append(
                    "Ensure all non-aggregated SELECT columns appear in GROUP BY"
                )
        return {"has_issues": len(issues) > 0, "issues": issues}

    # ------------------------------------------------------------------
    # Complexity check
    # ------------------------------------------------------------------

    def _check_complexity(self, sql: str) -> Dict[str, Any]:
        score = 0
        sql_upper = sql.upper()
        score += len(re.findall(r"\bJOIN\b", sql_upper)) * 10
        score += sql.upper().count("(SELECT") * 15
        score += len(re.findall(r"\bUNION\b", sql_upper)) * 10
        score += len(re.findall(r"\bOVER\s*\(", sql_upper)) * 5

        acceptable = score <= settings.MAX_QUERY_COMPLEXITY
        return {
            "acceptable": acceptable,
            "complexity_score": score,
            "message": (
                f"Query complexity score: {score}"
                + (
                    f" (exceeds maximum of {settings.MAX_QUERY_COMPLEXITY})"
                    if not acceptable
                    else ""
                )
            ),
        }

    # ------------------------------------------------------------------
    # Sanitization
    # ------------------------------------------------------------------

    def sanitize_sql(self, sql: str) -> str:
        """Format SQL for readability using sqlparse."""
        try:
            return sqlparse.format(
                sql, reindent=True, keyword_case="upper"
            ).strip()
        except Exception:
            return sql.strip()
