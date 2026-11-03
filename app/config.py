"""
Configuration management using Pydantic Settings.
Loads configuration from environment variables.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Any
import json
import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

# Explicitly load .env into os.environ for external libraries like LangChain
load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )
    
    # Database Configuration
    DATABASE_URL: str = "sqlite:///./sql_agent.db"
    
    # Security Settings
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    CONNECTION_ENCRYPTION_KEY: str
    
    # Groq Configuration
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = ""
    GROQ_FAST_MODEL: str = ""
    
    # LangSmith Observability
    LANGSMITH_TRACING: str = "false"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "sql_agent"
    
    # Application Settings
    APP_NAME: str = "AI SQL Agent"
    DEBUG: bool = False
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8000"

    @field_validator("ALLOWED_ORIGINS", mode="after")
    @classmethod
    def parse_allowed_origins(cls, v: str) -> List[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("SECRET_KEY", mode="after")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32 or "change-in-production" in v or "your-secret" in v:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters and must not contain insecure placeholder values"
            )
        return v

    @field_validator("CONNECTION_ENCRYPTION_KEY", mode="after")
    @classmethod
    def validate_connection_encryption_key(cls, v: str) -> str:
        try:
            Fernet(v.encode() if isinstance(v, str) else v)
        except Exception:
            raise ValueError(
                "CONNECTION_ENCRYPTION_KEY must construct a valid Fernet key"
            ) from None
        return v

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        try:
            url = make_url(v)
        except Exception:
            raise ValueError("DATABASE_URL is not a valid SQLAlchemy URL") from None

        if url.get_backend_name() == "postgres":
            raise ValueError("Use the postgresql:// scheme, not postgres://")

        if url.get_backend_name() == "sqlite":
            return v
        if url.get_backend_name() == "postgresql":
            if url.host not in ("localhost", "127.0.0.1", "::1"):
                sslmode = url.query.get("sslmode")
                if sslmode is None:
                    query_dict = dict(url.query)
                    query_dict["sslmode"] = "require"
                    url = url.set(query=query_dict)
                    return url.render_as_string(hide_password=False)
                if str(sslmode).lower() in ("disable", "allow", "prefer"):
                    raise ValueError(
                        "Remote PostgreSQL connection requires secure sslmode (disable, allow, prefer not allowed)"
                    )
        return url.render_as_string(hide_password=False) if url.get_backend_name() == "postgresql" else v
    
    # SQL Agent Settings
    MAX_QUERY_COMPLEXITY: int = 100
    QUERY_TIMEOUT_SECONDS: int = 30
    ENABLE_WRITE_OPERATIONS: bool = False
    ENABLE_DELETE_OPERATIONS: bool = False
    ENABLE_DDL_OPERATIONS: bool = False
    
    # GitHub OAuth (Optional)
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/auth/github/callback"


# Global settings instance
settings = Settings()
