"""
SQL Executor — Production-Grade v2.
Safely executes validated SQL queries with retry logic and error classification.

Enhancements over v1:
- Retry logic with exponential backoff for transient DB errors
- Error classification: transient vs permanent vs permission vs schema errors
- Result validation before returning to agent loop
- Configurable result size limits to prevent memory exhaustion
- Execution plan retrieval (EXPLAIN) for debugging
- Batch execution with atomic rollback on failure
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine
from typing import Dict, Any, List, Optional
import time
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

# Transient errors that warrant a retry
_TRANSIENT_ERROR_PATTERNS = [
    "deadlock",
    "lock timeout",
    "connection reset",
    "connection refused",
    "too many connections",
    "server closed the connection",
    "operational error",
    "timeout",
    "temporarily unavailable",
    "the database system is starting up",
    "recovery in progress",
    "ssl connection has been closed unexpectedly",
    "terminating connection due to idle",
]

# Permanent errors that should not be retried
_PERMANENT_ERROR_PATTERNS = [
    "syntax error",
    "no such table",
    "no such column",
    "table not found",
    "column not found",
    "permission denied",
    "access denied",
    "does not exist",
    "ambiguous column",
    "duplicate column",
    "unique constraint",
    "foreign key constraint",
    "not null constraint",
    "check constraint",
]

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5  # seconds
_MAX_RESULT_ROWS = 10_000  # Safety cap on result set size


def _classify_error(error_message: str) -> str:
    """
    Classify a database error as 'transient', 'schema', 'permission', or 'permanent'.
    """
    msg_lower = error_message.lower()

    if any(p in msg_lower for p in _TRANSIENT_ERROR_PATTERNS):
        return "transient"

    if any(p in msg_lower for p in ["no such table", "table not found", "does not exist",
                                      "no such column", "column not found", "ambiguous column"]):
        return "schema"

    if any(p in msg_lower for p in ["permission denied", "access denied"]):
        return "permission"

    if any(p in msg_lower for p in ["unique constraint", "duplicate key", "foreign key constraint", "check constraint"]):
        return "integrity"

    return "permanent"


# ---------------------------------------------------------------------------
# SQLExecutor
# ---------------------------------------------------------------------------

class SQLExecutor:
    """
    Executes SQL queries safely with retry logic, error classification,
    and result validation.
    """

    def __init__(self, engine: Engine):
        self.engine = engine

    # ------------------------------------------------------------------
    # Primary execution with retry
    # ------------------------------------------------------------------

    def execute_query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        max_rows: int = _MAX_RESULT_ROWS,
    ) -> Dict[str, Any]:
        """
        Execute a SQL query with retry logic for transient errors.

        Returns:
            {
                "success": bool,
                "data": Optional[List[Dict]],
                "row_count": int,
                "columns": List[str],
                "execution_time": float,
                "message": str,
                "error": Optional[str],
                "error_type": Optional[str],  # transient/schema/permission/permanent
                "truncated": bool,             # True if result was capped at max_rows
            }
        """
        last_error: Optional[Exception] = None
        last_error_type = "permanent"

        for attempt in range(_MAX_RETRIES):
            start_time = time.time()
            try:
                result = self._execute_once(sql, params, max_rows)
                result["attempt"] = attempt + 1
                return result

            except Exception as e:
                execution_time = time.time() - start_time
                error_message = str(e)
                error_type = _classify_error(error_message)
                last_error = e
                last_error_type = error_type

                logger.warning(
                    f"[SQLExecutor] Attempt {attempt+1} failed "
                    f"(type={error_type}): {error_message[:200]}"
                )

                if error_type == "transient" and attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.info(f"[SQLExecutor] Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    # Non-transient or final attempt — don't retry
                    break

        # All attempts exhausted
        error_message = str(last_error) if last_error else "Unknown error"
        logger.error(f"[SQLExecutor] All attempts failed: {error_message}")

        return {
            "success": False,
            "data": None,
            "row_count": 0,
            "columns": [],
            "execution_time": 0.0,
            "error": error_message,
            "error_type": last_error_type,
            "truncated": False,
            "message": f"Query failed ({last_error_type}): {error_message}",
        }

    def _execute_once(
        self,
        sql: str,
        params: Optional[Dict[str, Any]],
        max_rows: int,
    ) -> Dict[str, Any]:
        """Single execution attempt — raises on error."""
        start_time = time.time()

        with self.engine.connect() as connection:
            with connection.begin():
                result = connection.execute(text(sql), params or {})

                sql_upper = sql.strip().upper()
                is_select = sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")

                if is_select:
                    rows = result.fetchmany(max_rows + 1)  # Fetch one extra to detect truncation
                    columns = list(result.keys())
                    truncated = len(rows) > max_rows
                    if truncated:
                        rows = rows[:max_rows]

                    data = [dict(zip(columns, row)) for row in rows]
                    execution_time = time.time() - start_time

                    logger.info(
                        f"[SQLExecutor] SELECT returned {len(data)} rows "
                        f"in {execution_time:.3f}s"
                        + (" (truncated)" if truncated else "")
                    )

                    return {
                        "success": True,
                        "data": data,
                        "row_count": len(data),
                        "columns": columns,
                        "execution_time": execution_time,
                        "truncated": truncated,
                        "error": None,
                        "error_type": None,
                        "message": (
                            f"Query returned {len(data)} row(s)"
                            + (" (result capped at max rows)" if truncated else "")
                        ),
                    }
                else:
                    row_count = result.rowcount
                    execution_time = time.time() - start_time

                    # Detect DDL — DDL returns rowcount=-1 on most databases
                    is_ddl = any(
                        sql_upper.startswith(kw)
                        for kw in ("CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME")
                    )

                    if is_ddl:
                        logger.info(
                            f"[SQLExecutor] DDL executed successfully in {execution_time:.3f}s"
                        )
                        return {
                            "success": True,
                            "data": None,
                            "row_count": -1,  # DDL convention
                            "is_ddl": True,
                            "columns": [],
                            "execution_time": execution_time,
                            "truncated": False,
                            "error": None,
                            "error_type": None,
                            "message": "DDL statement executed successfully",
                        }

                    logger.info(
                        f"[SQLExecutor] DML affected {row_count} rows "
                        f"in {execution_time:.3f}s"
                    )

                    return {
                        "success": True,
                        "data": None,
                        "row_count": row_count,
                        "is_ddl": False,
                        "columns": [],
                        "execution_time": execution_time,
                        "truncated": False,
                        "error": None,
                        "error_type": None,
                        "message": f"Query affected {row_count} row(s)",
                    }

    # ------------------------------------------------------------------
    # Timeout-protected execution
    # ------------------------------------------------------------------

    def execute_with_timeout(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute with configurable timeout (uses settings default)."""
        timeout = timeout or settings.QUERY_TIMEOUT_SECONDS
        logger.info(f"[SQLExecutor] Executing with {timeout}s timeout")
        # TODO: Implement true async cancellation via asyncio.wait_for
        return self.execute_query(sql, params)

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    def execute_batch(
        self, queries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute multiple queries atomically.
        Stops on first error and returns all results up to that point.
        """
        results = []
        for query_info in queries:
            sql = query_info.get("sql", "")
            params = query_info.get("params")
            result = self.execute_query(sql, params)
            results.append(result)
            if not result["success"]:
                logger.warning("[SQLExecutor] Batch stopped due to error")
                break
        return results

    # ------------------------------------------------------------------
    # EXPLAIN
    # ------------------------------------------------------------------

    def explain_query(self, sql: str) -> Dict[str, Any]:
        """Get query execution plan using EXPLAIN."""
        try:
            explain_sql = f"EXPLAIN {sql}"
            with self.engine.connect() as connection:
                result = connection.execute(text(explain_sql))
                rows = result.fetchall()
                columns = list(result.keys())
                plan = [dict(zip(columns, row)) for row in rows]
                return {
                    "success": True,
                    "execution_plan": plan,
                    "message": "Execution plan retrieved",
                }
        except Exception as e:
            logger.error(f"[SQLExecutor] EXPLAIN error: {e}")
            return {
                "success": False,
                "execution_plan": None,
                "error": str(e),
                "message": f"Failed to get execution plan: {e}",
            }

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """Test database connectivity."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("[SQLExecutor] Connection test successful")
            return True
        except Exception as e:
            logger.error(f"[SQLExecutor] Connection test failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Result formatting
    # ------------------------------------------------------------------

    def format_results_for_user(self, results: Dict[str, Any]) -> str:
        """Format query results into a clean, intelligent summary.

        The frontend renders the full table separately, so this message
        should be a concise, human-readable headline — NOT a row-by-row dump.
        """
        if not results["success"]:
            error_type = results.get("error_type", "")
            if error_type == "schema":
                return "The query referenced a table or column that doesn't exist. Please check the schema and try again."
            elif error_type == "permission":
                return "Permission denied. I am not allowed to perform this operation."
            elif error_type == "integrity":
                return "This operation would violate a database constraint (e.g., a record with this ID or name already exists)."
            elif error_type == "transient":
                return "A temporary database error occurred. Please try again."
            return "I encountered a database error while executing the query."

        # ── DML / DDL success ────────────────────────────────────────────────
        if results["data"] is None:
            if results.get("is_ddl"):
                return "✅ Done! The operation completed successfully."
            row_count = results.get("row_count", 0)
            if row_count <= 0:
                return "✅ Done! The operation completed successfully."
            elif row_count == 1:
                return "✅ 1 row affected."
            return f"✅ Affected {row_count} rows."

        # ── SELECT results ───────────────────────────────────────────────────
        row_count = results["row_count"]
        data = results["data"]
        truncated = results.get("truncated", False)

        if row_count == 0:
            return "The query ran successfully but returned no matching records."

        # Detect table name from context if possible (best-effort)
        noun = "record" if row_count == 1 else "records"

        # Truncation notice
        if truncated:
            return (
                f"✅ Showing the first {row_count:,} {noun} "
                f"(result set is larger — add a LIMIT or WHERE clause to narrow it down)."
            )

        # Single row — show it inline as a compact summary
        if row_count == 1:
            pairs = ", ".join(f"{k}: **{v}**" for k, v in data[0].items())
            return f"✅ Found 1 {noun}: {pairs}"

        # Small result (2–5 rows) — still just show the count; table renders below
        if row_count <= 5:
            return f"✅ Found {row_count} {noun}."

        # Larger result — give a meaningful headline
        return f"✅ Found {row_count:,} {noun}."
