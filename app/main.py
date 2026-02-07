"""
Main FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.core.middleware import log_requests_middleware, error_handler_middleware, setup_cors
from app.api.routes import auth, agent, database, connections
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered SQL Agent that enables non-technical users to interact with databases using natural language",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Setup CORS
setup_cors(app)

# Add middleware
app.middleware("http")(log_requests_middleware)
app.middleware("http")(error_handler_middleware)

# Include routers
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(database.router)
app.include_router(connections.router)  # Already has /connections prefix


@app.on_event("startup")
async def startup_event():
    """
    Application startup event.
    Initialize database and perform startup tasks.
    """
    logger.info("Starting AI SQL Agent application...")
    
    # Initialize database (create tables)
    init_db()
    logger.info("Database initialized")
    
    # Log configuration
    logger.info(f"Database URL: {settings.DATABASE_URL}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Write operations enabled: {settings.ENABLE_WRITE_OPERATIONS}")
    logger.info(f"Delete operations enabled: {settings.ENABLE_DELETE_OPERATIONS}")
    logger.info(f"DDL operations enabled: {settings.ENABLE_DDL_OPERATIONS}")
    
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """
    Application shutdown event.
    Cleanup resources.
    """
    logger.info("Shutting down AI SQL Agent application...")


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint - API health check.
    """
    return {
        "message": "AI SQL Agent API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health", tags=["Root"])
async def health_check():
    """
    Health check endpoint.
    """
    return {
        "status": "healthy",
        "database": "connected"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
