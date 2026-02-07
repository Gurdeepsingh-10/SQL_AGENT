"""
Pydantic schemas for database connections.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class ConnectionCreate(BaseModel):
    """Schema for creating a new database connection."""
    connection_name: str = Field(..., min_length=1, max_length=255, description="Friendly name for this connection")
    connection_url: str = Field(..., description="PostgreSQL connection URL (e.g., postgresql://user:pass@host:5432/db)")
    is_default: bool = Field(default=False, description="Set as default connection")


class ConnectionUpdate(BaseModel):
    """Schema for updating a connection."""
    connection_name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class ConnectionResponse(BaseModel):
    """Schema for connection response (without sensitive data)."""
    id: int
    connection_name: str
    is_active: bool
    is_default: bool
    created_at: datetime
    last_used_at: Optional[datetime]
    
    # Masked connection URL (show only host)
    connection_host: str
    
    class Config:
        from_attributes = True


class ConnectionTest(BaseModel):
    """Schema for testing a connection."""
    connection_url: str = Field(..., description="PostgreSQL connection URL to test")
