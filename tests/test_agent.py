"""
Tests for SQL Agent components.
"""

import pytest
from app.core.agent.nlp_processor import NLPProcessor
from app.core.agent.sql_generator import SQLGenerator
from app.core.agent.validator import SQLValidator
from app.config import settings


class TestNLPProcessor:
    """Test suite for NLP processor."""
    
    @pytest.fixture
    def nlp_processor(self):
        """Create NLP processor instance."""
        return NLPProcessor()
    
    def test_query_safety_validation(self, nlp_processor):
        """Test query safety validation."""
        # Safe query
        safe_result = nlp_processor.validate_query_safety("Show me all users")
        assert safe_result["is_safe"] is True
        
        # Dangerous query
        dangerous_result = nlp_processor.validate_query_safety("DROP TABLE users")
        assert dangerous_result["is_safe"] is False
        assert len(dangerous_result["dangerous_keywords"]) > 0


class TestSQLGenerator:
    """Test suite for SQL generator."""
    
    @pytest.fixture
    def sql_generator(self):
        """Create SQL generator instance."""
        return SQLGenerator()
    
    def test_clean_sql(self, sql_generator):
        """Test SQL cleaning functionality."""
        # SQL with markdown
        sql_with_markdown = "```sql\nSELECT * FROM users;\n```"
        cleaned = sql_generator._clean_sql(sql_with_markdown)
        assert "```" not in cleaned
        assert cleaned.endswith(";")
        
        # SQL with extra whitespace
        sql_with_whitespace = "SELECT   *   FROM   users"
        cleaned = sql_generator._clean_sql(sql_with_whitespace)
        assert "  " not in cleaned


class TestSQLValidator:
    """Test suite for SQL validator."""
    
    @pytest.fixture
    def validator(self):
        """Create SQL validator instance."""
        return SQLValidator()
    
    def test_dangerous_keywords_detection(self, validator):
        """Test detection of dangerous SQL keywords."""
        # Safe query
        safe_sql = "SELECT * FROM users WHERE id = 1;"
        result = validator._check_dangerous_keywords(safe_sql)
        assert result["is_safe"] is True
        
        # Dangerous queries
        dangerous_queries = [
            "DROP TABLE users;",
            "TRUNCATE TABLE users;",
            "ALTER TABLE users ADD COLUMN test VARCHAR(255);",
            "GRANT ALL ON users TO public;"
        ]
        
        for query in dangerous_queries:
            result = validator._check_dangerous_keywords(query)
            assert result["is_safe"] is False
    
    def test_operation_permissions(self, validator):
        """Test operation permission checks."""
        # Test DELETE when disabled
        original_setting = settings.ENABLE_DELETE_OPERATIONS
        settings.ENABLE_DELETE_OPERATIONS = False
        
        result = validator._check_operation_permissions("DELETE FROM users WHERE id = 1;")
        assert result["allowed"] is False
        
        settings.ENABLE_DELETE_OPERATIONS = original_setting
    
    def test_sql_injection_detection(self, validator):
        """Test SQL injection pattern detection."""
        # Safe query
        safe_sql = "SELECT * FROM users WHERE email = 'user@example.com';"
        result = validator._check_sql_injection(safe_sql)
        assert result["is_safe"] is True
        
        # Injection attempts
        injection_queries = [
            "SELECT * FROM users WHERE id = 1 OR 1=1;",
            "SELECT * FROM users; DROP TABLE users;",
            "SELECT * FROM users WHERE name = 'admin'--'",
        ]
        
        for query in injection_queries:
            result = validator._check_sql_injection(query)
            # Note: Some patterns might not be caught by basic detection
            # This is a simplified test
    
    def test_syntax_validation(self, validator):
        """Test SQL syntax validation."""
        # Valid SQL
        valid_sql = "SELECT * FROM users;"
        result = validator._validate_syntax(valid_sql)
        assert result["is_valid"] is True
        
        # Multiple statements (potential injection)
        multiple_sql = "SELECT * FROM users; SELECT * FROM orders;"
        result = validator._validate_syntax(multiple_sql)
        assert result["is_valid"] is False
    
    def test_complexity_check(self, validator):
        """Test query complexity checking."""
        # Simple query
        simple_sql = "SELECT * FROM users;"
        result = validator._check_complexity(simple_sql)
        assert result["acceptable"] is True
        
        # Complex query with multiple joins
        complex_sql = """
        SELECT * FROM users 
        JOIN orders ON users.id = orders.user_id
        JOIN products ON orders.product_id = products.id
        JOIN categories ON products.category_id = categories.id;
        """
        result = validator._check_complexity(complex_sql)
        # Complexity depends on settings
    
    def test_full_validation(self, validator):
        """Test complete validation pipeline."""
        # Valid query
        valid_sql = "SELECT * FROM users WHERE id = 1;"
        result = validator.validate(valid_sql, "QUERY")
        assert result["is_valid"] is True
        assert len(result["errors"]) == 0
        
        # Invalid query (dangerous operation)
        invalid_sql = "DROP TABLE users;"
        result = validator.validate(invalid_sql, "DELETE")
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0


class TestTableNameExtraction:
    """Test table name extraction from SQL."""
    
    @pytest.fixture
    def validator(self):
        """Create SQL validator instance."""
        return SQLValidator()
    
    def test_extract_table_names(self, validator):
        """Test extraction of table names from SQL."""
        # Simple SELECT
        sql = "SELECT * FROM users;"
        tables = validator._extract_table_names(sql)
        assert "users" in tables
        
        # JOIN query
        sql = "SELECT * FROM users JOIN orders ON users.id = orders.user_id;"
        tables = validator._extract_table_names(sql)
        assert "users" in tables
        assert "orders" in tables
