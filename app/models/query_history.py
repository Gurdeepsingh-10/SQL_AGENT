"""
Query history model for tracking user queries and agent responses.
"""

from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class QueryHistory(Base):
    """Model for storing query history and agent execution logs."""
    
    __tablename__ = "query_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Query information
    natural_language_query = Column(Text, nullable=False)
    generated_sql = Column(Text)
    intent = Column(String)  # QUERY, INSERT, UPDATE, DELETE, SCHEMA_INFO
    
    # Execution results
    success = Column(Boolean, default=False)
    error_message = Column(Text)
    execution_time = Column(Float)  # Time in seconds
    result_count = Column(Integer)  # Number of rows returned/affected
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship to user
    user = relationship("User", back_populates="query_history")
    
    def __repr__(self):
        return f"<QueryHistory(id={self.id}, user_id={self.user_id}, intent={self.intent}, success={self.success})>"
