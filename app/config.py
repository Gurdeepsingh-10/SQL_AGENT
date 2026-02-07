"""
Configuration management using Pydantic Settings.
Loads configuration from environment variables.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import List, Any
import json


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database Configuration
    DATABASE_URL: str = "sqlite:///./sql_agent.db"
    
    # Security Settings
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Groq Configuration
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama3-70b-8192"  # Default to Llama 3 70B
    
    # Application Settings
    APP_NAME: str = "AI SQL Agent"
    DEBUG: bool = True
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8000"

    @field_validator("ALLOWED_ORIGINS", mode="after")
    @classmethod
    def parse_allowed_origins(cls, v: str) -> List[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    # SQL Agent Settings
    MAX_QUERY_COMPLEXITY: int = 100
    QUERY_TIMEOUT_SECONDS: int = 30
    ENABLE_WRITE_OPERATIONS: bool = True
    ENABLE_DELETE_OPERATIONS: bool = False
    ENABLE_DDL_OPERATIONS: bool = False
    
    # GitHub OAuth (Optional)
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/auth/github/callback"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore unknown fields from .env


# Global settings instance
settings = Settings()
