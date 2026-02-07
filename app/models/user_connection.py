"""
User database connection model.
Stores user's target database credentials for NLP queries.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class UserConnection(Base):
    """Model for storing user's target database connections."""
    
    __tablename__ = "user_connections"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Connection details
    connection_name = Column(String(255), nullable=False)  # User-friendly name
    connection_url = Column(Text, nullable=False)  # Encrypted database URL
    
    # Status
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)  # Default connection for this user
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="connections")
