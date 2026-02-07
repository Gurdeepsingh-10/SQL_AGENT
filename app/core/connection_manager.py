"""
Dynamic database connection manager.
Handles multiple user database connections with caching and encryption.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from typing import Dict, Optional
from cryptography.fernet import Fernet
import os
from app.config import settings
from app.utils.logger import logger


class ConnectionManager:
    """Manages dynamic database connections for users."""
    
    def __init__(self):
        """Initialize connection manager with encryption."""
        # Generate or load encryption key for connection strings
        self.encryption_key = os.getenv("CONNECTION_ENCRYPTION_KEY", Fernet.generate_key())
        if isinstance(self.encryption_key, str):
            self.encryption_key = self.encryption_key.encode()
        self.cipher = Fernet(self.encryption_key)
        
        # Cache for database engines (connection_id -> Engine)
        self._engine_cache: Dict[int, Engine] = {}
        
    def encrypt_connection_url(self, url: str) -> str:
        """Encrypt a database connection URL."""
        return self.cipher.encrypt(url.encode()).decode()
    
    def decrypt_connection_url(self, encrypted_url: str) -> str:
        """Decrypt a database connection URL."""
        return self.cipher.decrypt(encrypted_url.encode()).decode()
    
    def test_connection(self, connection_url: str) -> tuple[bool, Optional[str]]:
        """
        Test if a database connection is valid.
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        try:
            engine = create_engine(connection_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return True, None
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False, str(e)
    
    def get_engine(self, connection_id: int, connection_url: str) -> Engine:
        """
        Get or create a SQLAlchemy engine for a connection.
        Uses caching for performance.
        
        Args:
            connection_id: ID of the connection
            connection_url: Decrypted connection URL
            
        Returns:
            SQLAlchemy Engine instance
        """
        # Check cache first
        if connection_id in self._engine_cache:
            engine = self._engine_cache[connection_id]
            # Verify engine is still alive
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return engine
            except Exception:
                # Engine is dead, remove from cache
                logger.warning(f"Cached engine for connection {connection_id} is dead, recreating")
                del self._engine_cache[connection_id]
        
        # Create new engine
        logger.info(f"Creating new engine for connection {connection_id}")
        engine = create_engine(
            connection_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=settings.DEBUG
        )
        
        # Cache it
        self._engine_cache[connection_id] = engine
        return engine
    
    def close_connection(self, connection_id: int):
        """Close and remove a connection from cache."""
        if connection_id in self._engine_cache:
            logger.info(f"Closing engine for connection {connection_id}")
            self._engine_cache[connection_id].dispose()
            del self._engine_cache[connection_id]
    
    def close_all_connections(self):
        """Close all cached connections."""
        logger.info("Closing all cached database connections")
        for connection_id, engine in self._engine_cache.items():
            engine.dispose()
        self._engine_cache.clear()


# Global connection manager instance
connection_manager = ConnectionManager()
