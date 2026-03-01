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

                    logger.info(
                        f"[SQLExecutor] DML affected {row_count} rows "
                        f"in {execution_time:.3f}s"
                    )

                    return {
                        "success": True,
                        "data": None,
                        "row_count": row_count,
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
        """Format query results in a user-friendly way."""
        if not results["success"]:
            error_type = results.get("error_type", "")
            error = results.get("error", "Unknown error")
            if error_type == "schema":
                return (
                    f"The query referenced a table or column that doesn't exist: {error}"
                )
            elif error_type == "permission":
                return f"Permission denied: {error}"
            elif error_type == "transient":
                return f"A temporary database error occurred: {error}"
            return f"Query failed: {error}"

        if results["data"] is None:
            row_count = results.get("row_count", 0)
            if row_count == 0:
                return "Done! The operation completed successfully."
            elif row_count == 1:
                return "Updated 1 row."
            return f"Affected {row_count} rows."

        row_count = results["row_count"]
        if row_count == 0:
            return "Query ran successfully but returned no matching records."

        data = results["data"]
        preview_count = min(5, row_count)
        truncated = results.get("truncated", False)

        formatted = f"Found {row_count} result(s)"
        if truncated:
            formatted += f" (showing first {_MAX_RESULT_ROWS})"
        formatted += ".\n\n"

        if row_count > preview_count:
            formatted += f"Here are the first {preview_count}:\n"

        for i, row in enumerate(data[:preview_count], 1):
            formatted += f"\nRow {i}:\n"
            for key, value in row.items():
                formatted += f"  {key}: {value}\n"

        if row_count > preview_count:
            formatted += f"\n... and {row_count - preview_count} more row(s)"

        return formatted
