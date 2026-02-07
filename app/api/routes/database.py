"""
Database introspection routes for schema information.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db, engine
from app.schemas.database import TableListResponse, SchemaResponse, TableSchema, ColumnInfo
from app.models.user import User
from app.api.deps import get_current_user
from app.core.agent.schema_inspector import SchemaInspector
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/db", tags=["Database"])

# Initialize schema inspector
schema_inspector = SchemaInspector(engine)


@router.get("/tables", response_model=TableListResponse)
async def get_tables(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get list of all tables in the database.
    
    Args:
        current_user: Authenticated user
        db: Database session
        
    Returns:
        List of table names
    """
    try:
        tables = schema_inspector.get_all_tables()
        
        logger.info(f"User {current_user.email} requested table list: {len(tables)} tables")
        
        return TableListResponse(
            tables=tables,
            total=len(tables)
        )
    
    except Exception as e:
        logger.error(f"Error getting table list: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve table list: {str(e)}"
        )


@router.get("/schema/{table_name}", response_model=SchemaResponse)
async def get_table_schema(
    table_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed schema information for a specific table.
    
    Args:
        table_name: Name of the table
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Table schema with columns and metadata
    """
    try:
        # Check if table exists
        if not schema_inspector.validate_table_exists(table_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Table '{table_name}' not found"
            )
        
        # Get schema
        schema_data = schema_inspector.get_table_schema(table_name)
        
        # Convert to Pydantic model
        columns = [ColumnInfo(**col) for col in schema_data['columns']]
        
        table_schema = TableSchema(
            table_name=schema_data['table_name'],
            columns=columns,
            row_count=schema_data.get('row_count')
        )
        
        logger.info(f"User {current_user.email} requested schema for table: {table_name}")
        
        return SchemaResponse(table=table_schema)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting schema for table {table_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve table schema: {str(e)}"
        )


@router.post("/schema/refresh")
async def refresh_schema_cache(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Clear and refresh the schema cache.
    
    Args:
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Success message
    """
    try:
        schema_inspector.clear_cache()
        
        # Rebuild cache
        schema_inspector.get_full_schema()
        
        logger.info(f"User {current_user.email} refreshed schema cache")
        
        return {
            "success": True,
            "message": "Schema cache refreshed successfully"
        }
    
    except Exception as e:
        logger.error(f"Error refreshing schema cache: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh schema cache: {str(e)}"
        )
