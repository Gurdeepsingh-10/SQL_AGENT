"""
SQL Agent routes for natural language query processing.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db, engine
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse, QueryHistoryResponse, QueryHistoryItem
from app.models.user import User
from app.models.query_history import QueryHistory
from app.api.deps import get_current_user
from app.core.agent.nlp_processor import NLPProcessor
from app.core.agent.sql_generator import SQLGenerator
from app.core.agent.validator import SQLValidator
from app.core.agent.executor import SQLExecutor
from app.core.agent.schema_inspector import SchemaInspector
from app.utils.logger import get_logger
import time

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["SQL Agent"])

# Initialize agent components
nlp_processor = NLPProcessor()
sql_generator = SQLGenerator()
schema_inspector = SchemaInspector(engine)
sql_validator = SQLValidator(schema_inspector)
sql_executor = SQLExecutor(engine)


@router.post("/query", response_model=AgentQueryResponse)
async def process_query(
    request: AgentQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Process natural language query through the SQL agent pipeline.
    
    Pipeline: NLP → Intent Classification → SQL Generation → Validation → Execution
    
    Args:
        request: Natural language query request with optional connection_id
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Query results or error message
    """
    from app.models.user_connection import UserConnection
    from app.core.connection_manager import connection_manager
    from datetime import datetime
    
    start_time = time.time()
    query_text = request.query
    connection_id = request.connection_id
    
    logger.info(f"Processing query from user {current_user.email}: {query_text}")
    
    # Get target database connection
    target_connection = None
    target_engine = None
    
    if connection_id:
        # User specified a connection
        target_connection = db.query(UserConnection).filter(
            UserConnection.id == connection_id,
            UserConnection.user_id == current_user.id,
            UserConnection.is_active == True
        ).first()
        
        if not target_connection:
            return AgentQueryResponse(
                success=False,
                message="Connection not found or inactive",
                error="Invalid connection_id"
            )
    else:
        # Use default connection
        target_connection = db.query(UserConnection).filter(
            UserConnection.user_id == current_user.id,
            UserConnection.is_default == True,
            UserConnection.is_active == True
        ).first()
        
        if not target_connection:
            return AgentQueryResponse(
                success=False,
                message="No default connection found. Please add a database connection first.",
                error="No connection available"
            )
    
    # Decrypt and get engine for target database
    try:
        decrypted_url = connection_manager.decrypt_connection_url(target_connection.connection_url)
        target_engine = connection_manager.get_engine(target_connection.id, decrypted_url)
        
        # Update last_used_at
        target_connection.last_used_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        logger.error(f"Failed to connect to target database: {str(e)}")
        return AgentQueryResponse(
            success=False,
            message="Failed to connect to target database",
            error=str(e)
        )
    
    # Initialize history record (saved to PRIMARY database)
    history = QueryHistory(
        user_id=current_user.id,
        natural_language_query=query_text
    )
    
    try:
        # Create agent components for TARGET database
        target_schema_inspector = SchemaInspector(target_engine)
        target_sql_validator = SQLValidator(target_schema_inspector)
        target_sql_executor = SQLExecutor(target_engine)
        
        # Step 1: Get schema context from TARGET database
        schema_context = target_schema_inspector.get_schema_context_for_llm()
        
        # Step 2: NLP Processing - Classify intent
        intent_result = nlp_processor.classify_intent(query_text, schema_context)
        
        if intent_result.get('intent') == NLPProcessor.INTENT_UNKNOWN:
            # Fallback: If intent is unknown, assume it's a general query or DDL
            # and let the SQL generator handle it.
            logger.warning("Intent classified as UNKNOWN, proceeding with SQL generation anyway.")
            intent_result['intent'] = "GENERAL"
        
        intent = intent_result['intent']
        entities = intent_result.get('entities', {})
        history.intent = intent
        
        # Step 3: Handle SCHEMA_INFO queries differently
        if intent == NLPProcessor.INTENT_SCHEMA_INFO:
            # Return schema information from TARGET database
            tables = target_schema_inspector.get_all_tables()
            execution_time = time.time() - start_time
            
            history.success = True
            history.execution_time = execution_time
            db.add(history)
            db.commit()
            
            return AgentQueryResponse(
                success=True,
                intent=intent,
                message=f"Database contains {len(tables)} tables: {', '.join(tables)}",
                results=[{"tables": tables}],
                result_count=len(tables),
                execution_time=execution_time
            )
        
        # Step 4: Generate SQL
        sql_result = sql_generator.generate_sql(
            query_text,
            intent,
            entities,
            schema_context
        )
        
        if not sql_result.get('sql'):
            history.success = False
            history.error_message = "Failed to generate SQL"
            history.execution_time = time.time() - start_time
            db.add(history)
            db.commit()
            
            return AgentQueryResponse(
                success=False,
                intent=intent,
                message="I couldn't generate a valid SQL query for your request.",
                error=sql_result.get('error', 'SQL generation failed')
            )
        
        generated_sql = sql_result['sql']
        history.generated_sql = generated_sql
        
        # Step 5: Validate SQL against TARGET database schema
        validation_result = target_sql_validator.validate(generated_sql, intent)
        
        if not validation_result['is_valid']:
            error_msg = '; '.join(validation_result['errors'])
            history.success = False
            history.error_message = error_msg
            history.execution_time = time.time() - start_time
            db.add(history)
            db.commit()
            
            return AgentQueryResponse(
                success=False,
                intent=intent,
                generated_sql=generated_sql,
                message="The generated query failed security validation.",
                error=error_msg
            )
        
        # Step 6: Execute SQL on TARGET database
        execution_result = target_sql_executor.execute_query(generated_sql)
        
        execution_time = time.time() - start_time
        
        # Update history (saved to PRIMARY database)
        history.success = execution_result['success']
        history.execution_time = execution_time
        history.result_count = execution_result.get('row_count', 0)
        
        if not execution_result['success']:
            history.error_message = execution_result.get('error', 'Execution failed')
        
        db.add(history)
        db.commit()
        
        # Step 7: Format response
        if execution_result['success']:
            return AgentQueryResponse(
                success=True,
                intent=intent,
                generated_sql=generated_sql,
                results=execution_result.get('data'),
                result_count=execution_result.get('row_count', 0),
                execution_time=execution_time,
                message=execution_result['message']
            )
        else:
            return AgentQueryResponse(
                success=False,
                intent=intent,
                generated_sql=generated_sql,
                message="Query execution failed.",
                error=execution_result.get('error', 'Unknown error'),
                execution_time=execution_time
            )
    
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        
        execution_time = time.time() - start_time
        history.success = False
        history.error_message = str(e)
        history.execution_time = execution_time
        db.add(history)
        db.commit()
        
        return AgentQueryResponse(
            success=False,
            message="An error occurred while processing your query.",
            error=str(e),
            execution_time=execution_time
        )


@router.get("/history", response_model=QueryHistoryResponse)
async def get_query_history(
    limit: int = 50,
    offset: int = 0,
    success_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get query history for the current user.
    
    Args:
        limit: Maximum number of records to return
        offset: Number of records to skip
        success_only: If True, only return successful queries
        current_user: Authenticated user
        db: Database session
        
    Returns:
        List of query history records
    """
    query = db.query(QueryHistory).filter(QueryHistory.user_id == current_user.id)
    
    if success_only:
        query = query.filter(QueryHistory.success == True)
    
    total = query.count()
    
    queries = query.order_by(QueryHistory.created_at.desc()).offset(offset).limit(limit).all()
    
    logger.info(f"Retrieved {len(queries)} history records for user {current_user.email}")
    
    return QueryHistoryResponse(
        total=total,
        queries=queries
    )
