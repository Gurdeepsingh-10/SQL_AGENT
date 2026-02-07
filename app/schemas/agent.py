"""
Pydantic schemas for SQL agent endpoints.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Any, Dict


class AgentQueryRequest(BaseModel):
    """Schema for natural language query request."""
    query: str = Field(..., min_length=1, max_length=1000, description="Natural language query")
    connection_id: Optional[int] = Field(None, description="Target database connection ID (uses default if not provided)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "Show me all users created in the last 7 days",
                "connection_id": 1
            }
        }


class AgentQueryResponse(BaseModel):
    """Schema for agent query response."""
    success: bool
    intent: Optional[str] = None
    generated_sql: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None
    result_count: Optional[int] = None
    execution_time: Optional[float] = None
    message: str
    error: Optional[str] = None


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
