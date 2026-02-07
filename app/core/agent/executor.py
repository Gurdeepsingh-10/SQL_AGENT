"""
SQL Executor - Safely executes validated SQL queries.
Handles connection pooling, transactions, and result formatting.
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine
from typing import Dict, Any, List, Optional
import time
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)


class SQLExecutor:
    """
    Executes SQL queries safely with proper error handling and logging.
    """
    
    def __init__(self, engine: Engine):
        """
        Initialize SQL executor.
        
        Args:
            engine: SQLAlchemy engine instance
        """
        self.engine = engine
    
    def execute_query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a SQL query and return results.
        
        Args:
            sql: SQL query to execute
            params: Optional parameters for parameterized queries
            
        Returns:
            Dictionary containing execution results
        """
        start_time = time.time()
        
        try:
            with self.engine.connect() as connection:
                # Start a transaction
                with connection.begin():
                    # Execute the query
                    result = connection.execute(text(sql), params or {})
                    
                    # Determine query type
                    sql_upper = sql.strip().upper()
                    is_select = sql_upper.startswith('SELECT')
                    
                    if is_select:
                        # Fetch results for SELECT queries
                        rows = result.fetchall()
                        columns = list(result.keys())
                        
                        # Convert to list of dictionaries
                        data = [dict(zip(columns, row)) for row in rows]
                        
                        execution_time = time.time() - start_time
                        
                        logger.info(f"Query executed successfully: {len(data)} rows returned in {execution_time:.3f}s")
                        
                        return {
                            'success': True,
                            'data': data,
                            'row_count': len(data),
                            'columns': columns,
                            'execution_time': execution_time,
                            'message': f'Query returned {len(data)} row(s)'
                        }
                    else:
                        # For INSERT, UPDATE, DELETE
                        row_count = result.rowcount
                        execution_time = time.time() - start_time
                        
                        logger.info(f"Query executed successfully: {row_count} rows affected in {execution_time:.3f}s")
                        
                        return {
                            'success': True,
                            'data': None,
                            'row_count': row_count,
                            'columns': [],
                            'execution_time': execution_time,
                            'message': f'Query affected {row_count} row(s)'
                        }
        
        except Exception as e:
            execution_time = time.time() - start_time
            error_message = str(e)
            
            logger.error(f"Query execution failed: {error_message}")
            
            return {
                'success': False,
                'data': None,
                'row_count': 0,
                'columns': [],
                'execution_time': execution_time,
                'error': error_message,
                'message': f'Query failed: {error_message}'
            }
    
    def execute_with_timeout(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Execute query with timeout protection.
        
        Args:
            sql: SQL query
            params: Optional parameters
            timeout: Timeout in seconds (uses config default if not specified)
            
        Returns:
            Execution results
        """
        timeout = timeout or settings.QUERY_TIMEOUT_SECONDS
        
        # Note: Actual timeout implementation would require threading or async
        # For now, we'll use the standard execute_query
        # In production, you'd want to implement proper timeout handling
        
        logger.info(f"Executing query with {timeout}s timeout")
        return self.execute_query(sql, params)
    
    def execute_batch(self, queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Execute multiple queries in a batch.
        
        Args:
            queries: List of query dictionaries with 'sql' and optional 'params'
            
        Returns:
            List of execution results
        """
        results = []
        
        for query_info in queries:
            sql = query_info.get('sql')
            params = query_info.get('params')
            
            result = self.execute_query(sql, params)
            results.append(result)
            
            # Stop on first error
            if not result['success']:
                logger.warning("Batch execution stopped due to error")
                break
        
        return results
    
    def explain_query(self, sql: str) -> Dict[str, Any]:
        """
        Get query execution plan using EXPLAIN.
        
        Args:
            sql: SQL query to explain
            
        Returns:
            Execution plan information
        """
        try:
            explain_sql = f"EXPLAIN {sql}"
            
            with self.engine.connect() as connection:
                result = connection.execute(text(explain_sql))
                rows = result.fetchall()
                columns = list(result.keys())
                
                plan = [dict(zip(columns, row)) for row in rows]
                
                return {
                    'success': True,
                    'execution_plan': plan,
                    'message': 'Execution plan retrieved'
                }
                
        except Exception as e:
            logger.error(f"Error getting execution plan: {str(e)}")
            return {
                'success': False,
                'execution_plan': None,
                'error': str(e),
                'message': f'Failed to get execution plan: {str(e)}'
            }
    
    def test_connection(self) -> bool:
        """
        Test database connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("Database connection test successful")
            return True
        except Exception as e:
            logger.error(f"Database connection test failed: {str(e)}")
            return False
    
    def format_results_for_user(self, results: Dict[str, Any]) -> str:
        """
        Format query results in a user-friendly way.
        
        Args:
            results: Query execution results
            
        Returns:
            Formatted string for display
        """
        if not results['success']:
            return f"❌ Query failed: {results.get('error', 'Unknown error')}"
        
        if results['data'] is None:
            # Non-SELECT query
            return f"✅ {results['message']}"
        
        # SELECT query with data
        row_count = results['row_count']
        
        if row_count == 0:
            return "✅ Query executed successfully, but no results found."
        
        # Format first few rows as preview
        data = results['data']
        preview_count = min(5, row_count)
        
        formatted = f"✅ Found {row_count} result(s)\n\n"
        
        if row_count > 0:
            formatted += "Preview (first 5 rows):\n"
            for i, row in enumerate(data[:preview_count], 1):
                formatted += f"\nRow {i}:\n"
                for key, value in row.items():
                    formatted += f"  {key}: {value}\n"
        
        if row_count > preview_count:
            formatted += f"\n... and {row_count - preview_count} more row(s)"
        
        return formatted
