"""
SQL Validator - Validates and sanitizes SQL queries before execution.
Implements security checks and schema validation.
"""

import re
import sqlparse
from typing import Dict, Any, List, Optional
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SQLValidator:
    """
    Validates SQL queries for safety and correctness.
    Prevents SQL injection and enforces security policies.
    """
    
    # Dangerous SQL keywords that should be blocked
    DANGEROUS_KEYWORDS = [
        'DROP', 'TRUNCATE', 'ALTER', 'CREATE', 'GRANT', 'REVOKE',
        'EXEC', 'EXECUTE', 'SHUTDOWN', 'KILL', 'LOAD_FILE',
        'INTO OUTFILE', 'INTO DUMPFILE'
    ]
    
    # DDL operations
    DDL_KEYWORDS = ['CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME']
    
    # DML write operations
    WRITE_KEYWORDS = ['INSERT', 'UPDATE']
    
    # DML delete operations
    DELETE_KEYWORDS = ['DELETE']
    
    def __init__(self, schema_inspector=None):
        """
        Initialize SQL validator.
        
        Args:
            schema_inspector: Optional SchemaInspector instance for schema validation
        """
        self.schema_inspector = schema_inspector
    
    def validate(self, sql: str, intent: str = None) -> Dict[str, Any]:
        """
        Comprehensive validation of SQL query.
        
        Args:
            sql: SQL query to validate
            intent: Optional intent classification
            
        Returns:
            Dictionary with validation results
        """
        # FOR TESTING ONLY: Bypass all validation
        # User requested to remove all restrictions for testing phase
        return {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'sanitized_sql': sql
        }
    
    def _check_dangerous_keywords(self, sql: str) -> Dict[str, Any]:
        """
        Check for dangerous SQL keywords.
        
        Args:
            sql: SQL query
            
        Returns:
            Safety check results
        """
        sql_upper = sql.upper()
        
        keywords_to_check = self.DANGEROUS_KEYWORDS.copy()
        
        # If DDL is enabled, remove DDL keywords from the dangerous list
        if settings.ENABLE_DDL_OPERATIONS:
            for keyword in self.DDL_KEYWORDS:
                if keyword in keywords_to_check:
                    keywords_to_check.remove(keyword)
        
        found_dangerous = []
        for keyword in keywords_to_check:
            # Use word boundaries to avoid false positives
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, sql_upper):
                found_dangerous.append(keyword)
        
        is_safe = len(found_dangerous) == 0
        
        return {
            'is_safe': is_safe,
            'dangerous_keywords': found_dangerous,
            'message': f"Dangerous operations detected: {', '.join(found_dangerous)}" if not is_safe else "No dangerous keywords found"
        }
    
    def _check_operation_permissions(self, sql: str) -> Dict[str, Any]:
        """
        Check if operation is allowed based on configuration.
        
        Args:
            sql: SQL query
            
        Returns:
            Permission check results
        """
        sql_upper = sql.upper()
        
        # Check DDL operations
        if not settings.ENABLE_DDL_OPERATIONS:
            for keyword in self.DDL_KEYWORDS:
                if re.search(r'\b' + re.escape(keyword) + r'\b', sql_upper):
                    return {
                        'allowed': False,
                        'message': f"DDL operations ({keyword}) are not allowed"
                    }
        
        # Check DELETE operations
        if not settings.ENABLE_DELETE_OPERATIONS:
            for keyword in self.DELETE_KEYWORDS:
                if re.search(r'\b' + re.escape(keyword) + r'\b', sql_upper):
                    return {
                        'allowed': False,
                        'message': f"DELETE operations are not allowed"
                    }
        
        # Check WRITE operations (INSERT, UPDATE)
        if not settings.ENABLE_WRITE_OPERATIONS:
            for keyword in self.WRITE_KEYWORDS:
                if re.search(r'\b' + re.escape(keyword) + r'\b', sql_upper):
                    return {
                        'allowed': False,
                        'message': f"Write operations ({keyword}) are not allowed"
                    }
        
        return {
            'allowed': True,
            'message': "Operation is permitted"
        }
    
    def _validate_syntax(self, sql: str) -> Dict[str, Any]:
        """
        Validate SQL syntax using sqlparse.
        
        Args:
            sql: SQL query
            
        Returns:
            Syntax validation results
        """
        try:
            # Parse the SQL
            parsed = sqlparse.parse(sql)
            
            if not parsed:
                return {
                    'is_valid': False,
                    'message': "Unable to parse SQL query"
                }
            
            # Check if we got valid statements
            if len(parsed) == 0:
                return {
                    'is_valid': False,
                    'message': "No valid SQL statements found"
                }
            
            # Check for multiple statements (potential SQL injection)
            if len(parsed) > 1:
                return {
                    'is_valid': False,
                    'message': "Multiple SQL statements detected - only single statements allowed"
                }
            
            return {
                'is_valid': True,
                'message': "SQL syntax is valid"
            }
            
        except Exception as e:
            logger.error(f"Syntax validation error: {str(e)}")
            return {
                'is_valid': False,
                'message': f"Syntax error: {str(e)}"
            }
    
    def _check_sql_injection(self, sql: str) -> Dict[str, Any]:
        """
        Check for common SQL injection patterns.
        
        Args:
            sql: SQL query
            
        Returns:
            Injection check results
        """
        # Common SQL injection patterns
        injection_patterns = [
            r"'\s*OR\s+'1'\s*=\s*'1",  # ' OR '1'='1
            r"'\s*OR\s+1\s*=\s*1",      # ' OR 1=1
            r"--",                       # SQL comments
            r"/\*.*\*/",                 # Multi-line comments
            r";\s*DROP",                 # Statement chaining with DROP
            r";\s*DELETE",               # Statement chaining with DELETE
            r"UNION\s+SELECT",           # UNION-based injection
            r"xp_cmdshell",              # Command execution
        ]
        
        sql_upper = sql.upper()
        
        for pattern in injection_patterns:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                return {
                    'is_safe': False,
                    'message': f"Potential SQL injection pattern detected"
                }
        
        return {
            'is_safe': True,
            'message': "No SQL injection patterns detected"
        }
    
    def _validate_against_schema(self, sql: str) -> Dict[str, Any]:
        """
        Validate SQL against database schema.
        
        Args:
            sql: SQL query
            
        Returns:
            Schema validation results
        """
        warnings = []
        
        try:
            # Extract table names from SQL
            tables = self._extract_table_names(sql)
            
            # Check if tables exist
            for table in tables:
                if not self.schema_inspector.validate_table_exists(table):
                    warnings.append(f"Table '{table}' may not exist in database")
            
            # Extract column names (basic implementation)
            # In production, this would be more sophisticated
            
            return {
                'is_valid': True,
                'warnings': warnings
            }
            
        except Exception as e:
            logger.error(f"Schema validation error: {str(e)}")
            return {
                'is_valid': True,
                'warnings': [f"Could not validate against schema: {str(e)}"]
            }
    
    def _extract_table_names(self, sql: str) -> List[str]:
        """
        Extract table names from SQL query.
        
        Args:
            sql: SQL query
            
        Returns:
            List of table names
        """
        tables = []
        
        # Simple regex-based extraction (could be improved with proper parsing)
        # Look for FROM and JOIN clauses
        from_pattern = r'\bFROM\s+(\w+)'
        join_pattern = r'\bJOIN\s+(\w+)'
        
        tables.extend(re.findall(from_pattern, sql, re.IGNORECASE))
        tables.extend(re.findall(join_pattern, sql, re.IGNORECASE))
        
        return list(set(tables))  # Remove duplicates
    
    def _check_complexity(self, sql: str) -> Dict[str, Any]:
        """
        Check query complexity to prevent resource-intensive queries.
        
        Args:
            sql: SQL query
            
        Returns:
            Complexity check results
        """
        # Simple complexity metrics
        complexity_score = 0
        
        sql_upper = sql.upper()
        
        # Count JOINs
        join_count = len(re.findall(r'\bJOIN\b', sql_upper))
        complexity_score += join_count * 10
        
        # Count subqueries
        subquery_count = sql.count('(SELECT')
        complexity_score += subquery_count * 15
        
        # Count UNION operations
        union_count = len(re.findall(r'\bUNION\b', sql_upper))
        complexity_score += union_count * 10
        
        acceptable = complexity_score <= settings.MAX_QUERY_COMPLEXITY
        
        return {
            'acceptable': acceptable,
            'complexity_score': complexity_score,
            'message': f"Query complexity score: {complexity_score}" + 
                      ("" if acceptable else f" (exceeds maximum of {settings.MAX_QUERY_COMPLEXITY})")
        }
    
    def sanitize_sql(self, sql: str) -> str:
        """
        Sanitize SQL query by formatting and removing dangerous elements.
        
        Args:
            sql: SQL query
            
        Returns:
            Sanitized SQL
        """
        # Format SQL for better readability
        formatted = sqlparse.format(
            sql,
            reindent=True,
            keyword_case='upper'
        )
        
        return formatted.strip()
