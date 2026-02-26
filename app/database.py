"""
Database connection and session management.
Handles SQLAlchemy engine setup and session creation.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Create SQLAlchemy engine
# For SQLite, we need check_same_thread=False for FastAPI
if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )
else:
    # For PostgreSQL / Neon serverless pooler
    # pool_pre_ping   : validates connections after Neon cold-starts
    # pool_recycle    : recycle every 5 min to avoid stale connections after Neon auto-pause
    # connect_timeout : give Neon a few extra seconds to wake from a pause
    # pool_size/max_overflow kept low to stay within Neon free-tier connection limits
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=300,
        connect_args={"connect_timeout": 10},
    )

# Create SessionLocal class for database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for SQLAlchemy models
Base = declarative_base()


def get_db():
    """
    Dependency function to get database session.
    Yields a database session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database by creating all tables.
    Should be called on application startup.
    """
    Base.metadata.create_all(bind=engine)
