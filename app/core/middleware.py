"""
Middleware for error handling, logging, and CORS.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.utils.logger import get_logger
import time

logger = get_logger(__name__)


async def log_requests_middleware(request: Request, call_next):
    """
    Middleware to log all incoming requests and their processing time.
    """
    start_time = time.time()
    
    # Log request
    logger.info(f"Request: {request.method} {request.url.path}")
    
    # Process request
    response = await call_next(request)
    
    # Calculate processing time
    process_time = time.time() - start_time
    
    # Log response
    logger.info(f"Response: {response.status_code} - Time: {process_time:.3f}s")
    
    # Add custom header with processing time
    response.headers["X-Process-Time"] = str(process_time)
    
    return response


async def error_handler_middleware(request: Request, call_next):
    """
    Global error handler middleware to catch and format exceptions.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "An internal error occurred",
                "error": str(exc) if settings.DEBUG else "Internal server error"
            }
        )


def setup_cors(app):
    """
    Configure CORS middleware for the application.
    
    Args:
        app: FastAPI application instance
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
