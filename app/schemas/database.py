"""
Pydantic schemas for database introspection endpoints.
"""

from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class ColumnInfo(BaseModel):
    """Schema for database column information."""
    name: str
    type: str
    nullable: bool
    primary_key: bool
    foreign_key: Optional[str] = None
    default: Optional[Any] = None


class TableSchema(BaseModel):
    """Schema for database table structure."""
    table_name: str
    columns: List[ColumnInfo]
    row_count: Optional[int] = None


class TableListResponse(BaseModel):
    """Schema for list of database tables."""
    tables: List[str]
    total: int


class SchemaResponse(BaseModel):
    """Schema for detailed table schema response."""
    table: TableSchema
