"""
Database schema introspection module.
Extracts and caches database schema information for SQL generation.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from typing import Dict, List, Any, Optional
from app.utils.logger import get_logger
import json

logger = get_logger(__name__)


class SchemaInspector:
    """
    Inspects database schema and provides metadata for SQL generation.
    Implements caching to improve performance.
    """
    
    def __init__(self, engine: Engine):
        """
        Initialize schema inspector.
        
        Args:
            engine: SQLAlchemy engine instance
        """
        self.engine = engine
        self.inspector = inspect(engine)
        self._schema_cache: Optional[Dict[str, Any]] = None
        
    def get_all_tables(self) -> List[str]:
        """
        Get list of all table names in the database.
        
        Returns:
            List of table names
        """
        try:
            tables = self.inspector.get_table_names()
            logger.info(f"Found {len(tables)} tables in database")
            return tables
        except Exception as e:
            logger.error(f"Error getting table names: {str(e)}")
            return []
    
    def get_table_schema(self, table_name: str) -> Dict[str, Any]:
        """
        Get detailed schema information for a specific table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Dictionary containing table schema information
        """
        try:
            columns = self.inspector.get_columns(table_name)
            primary_keys = self.inspector.get_pk_constraint(table_name)
            foreign_keys = self.inspector.get_foreign_keys(table_name)
            
            # Build foreign key mapping
            fk_map = {}
            for fk in foreign_keys:
                for col in fk['constrained_columns']:
                    fk_map[col] = f"{fk['referred_table']}.{fk['referred_columns'][0]}"
            
            # Format column information
            column_info = []
            for col in columns:
                column_info.append({
                    'name': col['name'],
                    'type': str(col['type']),
                    'nullable': col['nullable'],
                    'primary_key': col['name'] in primary_keys.get('constrained_columns', []),
                    'foreign_key': fk_map.get(col['name']),
                    'default': str(col.get('default')) if col.get('default') else None
                })
            
            # Get row count
            row_count = self._get_row_count(table_name)
            
            schema = {
                'table_name': table_name,
                'columns': column_info,
                'row_count': row_count
            }
            
            logger.info(f"Retrieved schema for table: {table_name}")
            return schema
            
        except Exception as e:
            logger.error(f"Error getting schema for table {table_name}: {str(e)}")
            return {'table_name': table_name, 'columns': [], 'row_count': 0}
    
    def _get_row_count(self, table_name: str) -> int:
        """
        Get the number of rows in a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Number of rows
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                return count or 0
        except Exception as e:
            logger.error(f"Error getting row count for {table_name}: {str(e)}")
            return 0
    
    def get_full_schema(self) -> Dict[str, Any]:
        """
        Get complete database schema with all tables and columns.
        Results are cached for performance.
        
        Returns:
            Dictionary containing full database schema
        """
        if self._schema_cache is not None:
            logger.info("Returning cached schema")
            return self._schema_cache
        
        tables = self.get_all_tables()
        schema = {
            'tables': {},
            'total_tables': len(tables)
        }
        
        for table in tables:
            schema['tables'][table] = self.get_table_schema(table)
        
        self._schema_cache = schema
        logger.info(f"Cached full schema with {len(tables)} tables")
        
        return schema
    
    def clear_cache(self):
        """Clear the schema cache to force refresh on next access."""
        self._schema_cache = None
        logger.info("Schema cache cleared")
    
    def get_schema_context_for_llm(self) -> str:
        """
        Get a formatted schema description optimized for LLM context.
        
        Returns:
            Formatted string describing the database schema
        """
        schema = self.get_full_schema()
        
        context_parts = [
            "Database Schema Information:",
            f"Total Tables: {schema['total_tables']}\n"
        ]
        
        for table_name, table_info in schema['tables'].items():
            context_parts.append(f"Table: {table_name}")
            context_parts.append(f"  Rows: {table_info['row_count']}")
            context_parts.append("  Columns:")
            
            for col in table_info['columns']:
                col_desc = f"    - {col['name']} ({col['type']})"
                if col['primary_key']:
                    col_desc += " [PRIMARY KEY]"
                if col['foreign_key']:
                    col_desc += f" [FK -> {col['foreign_key']}]"
                if not col['nullable']:
                    col_desc += " [NOT NULL]"
                context_parts.append(col_desc)
            
            context_parts.append("")  # Empty line between tables
        
        return "\n".join(context_parts)
    
    def validate_table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the database.
        
        Args:
            table_name: Name of the table to check
            
        Returns:
            True if table exists, False otherwise
        """
        return table_name in self.get_all_tables()
    
    def validate_columns_exist(self, table_name: str, columns: List[str]) -> bool:
        """
        Check if specified columns exist in a table.
        
        Args:
            table_name: Name of the table
            columns: List of column names to check
            
        Returns:
            True if all columns exist, False otherwise
        """
        if not self.validate_table_exists(table_name):
            return False
        
        table_schema = self.get_table_schema(table_name)
        existing_columns = {col['name'] for col in table_schema['columns']}
        
        return all(col in existing_columns for col in columns)
