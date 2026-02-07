"""
API routes for managing user database connections.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from urllib.parse import urlparse

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.user_connection import UserConnection
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionUpdate,
    ConnectionResponse,
    ConnectionTest
)
from app.core.connection_manager import connection_manager
from app.utils.logger import logger

router = APIRouter(prefix="/connections", tags=["Connections"])


@router.post("/test", status_code=status.HTTP_200_OK)
async def test_connection(
    connection_data: ConnectionTest,
    current_user: User = Depends(get_current_user)
):
    """
    Test a database connection without saving it.
    """
    success, error = connection_manager.test_connection(connection_data.connection_url)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection test failed: {error}"
        )
    
    return {
        "success": True,
        "message": "Connection successful"
    }


@router.post("/add", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
async def add_connection(
    connection_data: ConnectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add a new database connection for the current user.
    """
    # Test connection first
    success, error = connection_manager.test_connection(connection_data.connection_url)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection test failed: {error}"
        )
    
    # If this is set as default, unset other defaults
    if connection_data.is_default:
        db.query(UserConnection).filter(
            UserConnection.user_id == current_user.id,
            UserConnection.is_default == True
        ).update({"is_default": False})
    
    # Encrypt the connection URL
    encrypted_url = connection_manager.encrypt_connection_url(connection_data.connection_url)
    
    # Create new connection
    new_connection = UserConnection(
        user_id=current_user.id,
        connection_name=connection_data.connection_name,
        connection_url=encrypted_url,
        is_default=connection_data.is_default
    )
    
    db.add(new_connection)
    db.commit()
    db.refresh(new_connection)
    
    logger.info(f"User {current_user.id} added new connection: {new_connection.id}")
    
    # Extract host for response
    parsed = urlparse(connection_data.connection_url)
    connection_host = parsed.hostname or "unknown"
    
    return ConnectionResponse(
        id=new_connection.id,
        connection_name=new_connection.connection_name,
        is_active=new_connection.is_active,
        is_default=new_connection.is_default,
        created_at=new_connection.created_at,
        last_used_at=new_connection.last_used_at,
        connection_host=connection_host
    )


@router.get("/list", response_model=List[ConnectionResponse])
async def list_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all database connections for the current user.
    """
    connections = db.query(UserConnection).filter(
        UserConnection.user_id == current_user.id
    ).all()
    
    result = []
    for conn in connections:
        # Decrypt to get host
        try:
            decrypted_url = connection_manager.decrypt_connection_url(conn.connection_url)
            parsed = urlparse(decrypted_url)
            connection_host = parsed.hostname or "unknown"
        except Exception:
            connection_host = "error"
        
        result.append(ConnectionResponse(
            id=conn.id,
            connection_name=conn.connection_name,
            is_active=conn.is_active,
            is_default=conn.is_default,
            created_at=conn.created_at,
            last_used_at=conn.last_used_at,
            connection_host=connection_host
        ))
    
    return result


@router.patch("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: int,
    connection_data: ConnectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a database connection.
    """
    connection = db.query(UserConnection).filter(
        UserConnection.id == connection_id,
        UserConnection.user_id == current_user.id
    ).first()
    
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found"
        )
    
    # Update fields
    if connection_data.connection_name is not None:
        connection.connection_name = connection_data.connection_name
    
    if connection_data.is_active is not None:
        connection.is_active = connection_data.is_active
        # Close cached engine if deactivating
        if not connection_data.is_active:
            connection_manager.close_connection(connection_id)
    
    if connection_data.is_default is not None and connection_data.is_default:
        # Unset other defaults
        db.query(UserConnection).filter(
            UserConnection.user_id == current_user.id,
            UserConnection.id != connection_id
        ).update({"is_default": False})
        connection.is_default = True
    
    db.commit()
    db.refresh(connection)
    
    # Extract host
    decrypted_url = connection_manager.decrypt_connection_url(connection.connection_url)
    parsed = urlparse(decrypted_url)
    connection_host = parsed.hostname or "unknown"
    
    return ConnectionResponse(
        id=connection.id,
        connection_name=connection.connection_name,
        is_active=connection.is_active,
        is_default=connection.is_default,
        created_at=connection.created_at,
        last_used_at=connection.last_used_at,
        connection_host=connection_host
    )


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a database connection.
    """
    connection = db.query(UserConnection).filter(
        UserConnection.id == connection_id,
        UserConnection.user_id == current_user.id
    ).first()
    
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found"
        )
    
    # Close cached engine
    connection_manager.close_connection(connection_id)
    
    db.delete(connection)
    db.commit()
    
    logger.info(f"User {current_user.id} deleted connection: {connection_id}")
    
    return None
