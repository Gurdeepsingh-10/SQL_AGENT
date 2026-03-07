"""
Pydantic schemas for SQL agent endpoints — Production-Grade v2.

Enhancements:
- Rich structured response with operation metadata
- Pagination support for large SELECT results
- DDL/DML summaries with table name and affected rows
- Structured error with type and suggested fix
- Execution time in milliseconds for frontend display
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Any, Dict


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class AgentQueryRequest(BaseModel):
    """Schema for natural language query request."""
    query: str = Field(..., min_length=1, max_length=1000, description="Natural language query")
    connection_id: Optional[int] = Field(
        None,
        description="Target database connection ID (uses default if not provided)"
    )
    confirmed: bool = Field(
        False,
        description="Set to True when the user has approved a DDL/DML confirmation modal"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Show me all users created in the last 7 days",
                "connection_id": 1,
                "confirmed": False,
            }
        }


# ---------------------------------------------------------------------------
# Rich response sub-models
# ---------------------------------------------------------------------------

class QueryMetadata(BaseModel):
    """Execution metadata for display in the frontend."""
    operation: str = Field(..., description="SQL operation type: SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, etc.")
    target_table: Optional[str] = Field(None, description="Primary table affected by the query")
    rows_affected: int = Field(0, description="Number of rows returned or affected")
    execution_time_ms: float = Field(0.0, description="Query execution time in milliseconds")
    truncated: bool = Field(False, description="True if result set was capped at max rows")
    total_rows: Optional[int] = Field(None, description="Total rows available (before truncation)")


class DDLSummary(BaseModel):
    """Summary of a DDL operation."""
    operation: str = Field(..., description="CREATE, ALTER, DROP, TRUNCATE, RENAME")
    object_type: str = Field("TABLE", description="TABLE, INDEX, VIEW, etc.")
    object_name: str = Field(..., description="Name of the created/altered/dropped object")
    details: Optional[str] = Field(None, description="Additional details (e.g., column count for CREATE)")


class DMLSummary(BaseModel):
    """Summary of a DML operation."""
    operation: str = Field(..., description="INSERT, UPDATE, DELETE")
    target_table: str = Field(..., description="Table that was modified")
    rows_affected: int = Field(0, description="Number of rows inserted/updated/deleted")
    confirmation: str = Field(..., description="Human-readable confirmation message")


class StructuredError(BaseModel):
    """Structured error with type and suggested fix."""
    error_type: str = Field(..., description="transient, schema, permission, validation, permanent")
    message: str = Field(..., description="Human-readable error message")
    problematic_part: Optional[str] = Field(None, description="The part of the query that caused the error")
    suggested_fix: Optional[str] = Field(None, description="Suggested correction")


class PaginationInfo(BaseModel):
    """Pagination metadata for large result sets."""
    page: int = Field(1, description="Current page (1-based)")
    page_size: int = Field(50, description="Rows per page")
    total_rows: int = Field(0, description="Total rows available")
    total_pages: int = Field(1, description="Total number of pages")
    has_next: bool = Field(False, description="Whether there are more pages")
    has_prev: bool = Field(False, description="Whether there are previous pages")


# ---------------------------------------------------------------------------
# Main response
# ---------------------------------------------------------------------------

class AgentQueryResponse(BaseModel):
    """Rich structured response for agent query endpoint."""
    success: bool

    # Intent and SQL
    intent: Optional[str] = None
    generated_sql: Optional[str] = None

    # Results (SELECT queries)
    results: Optional[List[Dict[str, Any]]] = None
    columns: Optional[List[str]] = None
    chart_config: Optional[Dict[str, Any]] = None

    # Rich metadata
    metadata: Optional[QueryMetadata] = None
    ddl_summary: Optional[DDLSummary] = None
    dml_summary: Optional[DMLSummary] = None
    pagination: Optional[PaginationInfo] = None

    # Legacy fields (kept for backward compatibility)
    result_count: Optional[int] = None
    execution_time: Optional[float] = None

    # Confirmation flow — set when DDL/DML needs user approval
    requires_confirmation: bool = False
    pending_sql: Optional[str] = None
    confirmation_risk: Optional[str] = None  # "CONFIRM" or "DANGER"

    # Response message
    message: str

    # Error (structured)
    error: Optional[str] = None
    structured_error: Optional[StructuredError] = None


# ---------------------------------------------------------------------------
# History schemas
# ---------------------------------------------------------------------------

class QueryHistoryItem(BaseModel):
    """Schema for a single query history item."""
    id: int
    natural_language_query: str
    generated_sql: Optional[str]
    intent: Optional[str]
    success: bool
    error_message: Optional[str]
    execution_time: Optional[float]
    result_count: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class QueryHistoryResponse(BaseModel):
    """Schema for query history list response."""
    total: int
    queries: List[QueryHistoryItem]
