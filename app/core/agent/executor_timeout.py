from sqlalchemy import text
from typing import Dict

class TimeoutExecutor:
    """Execute queries with timeout and fallback to pagination."""
    
    def execute_with_timeout(
        self, 
        engine, 
        sql: str, 
        timeout_ms: int = 1000
    ) -> Dict:
        """Execute query with timeout; if exceeded, return paginated results."""
        try:
            # Set connection timeout
            with engine.connect() as conn:
                conn = conn.execution_options(timeout=timeout_ms/1000)
                result = conn.execute(text(sql))
                # Using mapping to ensure dict-like access
                rows = [dict(row._mapping) for row in result]
                return {"success": True, "data": rows}
        
        except Exception as e:
            if "timeout" in str(e).lower():
                # Fallback: return paginated results
                paginated_sql = f"({sql}) LIMIT 100 OFFSET 0"
                with engine.connect() as conn:
                    result = conn.execute(text(paginated_sql))
                    rows = [dict(row._mapping) for row in result]
                    return {
                        "success": True,
                        "data": rows,
                        "paginated": True,
                        "message": "Results limited to 100 rows due to timeout"
                    }
            raise
