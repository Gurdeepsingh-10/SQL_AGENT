"""
Main FastAPI application entry point.
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.core.middleware import log_requests_middleware, error_handler_middleware, setup_cors
from app.api.routes import auth, agent, database, connections, dashboard
from app.utils.logger import get_logger

# ── Rate Limiting ─────────────────────────────────────────────────────────
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
    _RATE_LIMIT_AVAILABLE = True
except ImportError:
    limiter = None
    _RATE_LIMIT_AVAILABLE = False

logger = get_logger(__name__)

# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered SQL Agent that enables non-technical users to interact with databases using natural language",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Attach rate limiter state and error handler
if _RATE_LIMIT_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse('app/static/index.html')


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
    try:
        from app.database import engine
        from app.core.connection_manager import connection_manager
        connection_manager.close_all_connections()
        engine.dispose()
        logger.info("Database engines disposed")
    except Exception as e:
        logger.error(f"Error during shutdown cleanup: {str(e)}")


    return {
        "message": "AI SQL Agent API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "frontend": "/"
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
