from fastapi import FastAPI
from contextlib import asynccontextmanager
from sqlalchemy import text

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Warming up database connection pool...")
    from app.database import engine
    
    # Execute dummy queries to warm pool
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    
    yield
    
    # Shutdown
    engine.dispose()
