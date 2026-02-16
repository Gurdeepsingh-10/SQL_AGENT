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
from app.core.agent.graph import graph
from app.core.agent.nodes import current_engine_cv
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
    Process natural language query through the SQL agent pipeline (LangGraph).
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
    
    # Decrypt and get engine
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
    
    # Initialize history record
    history = QueryHistory(
        user_id=current_user.id,
        natural_language_query=query_text
    )
    
    try:
        # Set the current engine for the request context (used by graph nodes)
        token = current_engine_cv.set(target_engine)
        
        # Get schema context for the prompt
        # We still need this for the NLP/Gen steps. 
        # Alternatively we could make a node for this, but pre-fetching is fine.
        schema_inspector = SchemaInspector(target_engine)
        schema_context = schema_inspector.get_schema_context_for_llm()
        
        # Prepare graph inputs
        inputs = {
            "query": query_text,
            "schema_context": schema_context,
            "db_connection_id": target_connection.id if target_connection else None
        }
        
        # Generate a thread ID for the conversation
        # In a real app, this should avail of a session ID from the frontend or user context.
        # For now, we'll use the user ID + connection ID as a simple session key, 
        # or generate a new one per request if we don't want history persistence yet.
        # The user wants "proper genai project", so persistence per connection/user is good.
        thread_id = f"{current_user.id}_{target_connection.id}"
        
        # Invoke LangGraph
        result_state = await graph.ainvoke(
            inputs,
            config={"configurable": {"thread_id": thread_id}}
        )
        
        # Reset context var
        current_engine_cv.reset(token)
        
        # Process results
        execution_time = time.time() - start_time
        
        intent = result_state.get("intent", "UNKNOWN")
        error = result_state.get("error")
        sql_query = result_state.get("sql_query")
        sql_results = result_state.get("sql_results")
        
        # Populate history
        history.intent = intent
        history.generated_sql = sql_query
        history.success = error is None
        history.error_message = error
        history.execution_time = execution_time
        history.result_count = len(sql_results) if sql_results else 0
        
        db.add(history)
        db.commit()
        
        # Determine final message
        final_message = "Query executed successfully"
        if result_state.get("messages"):
            # Get the last message content
            final_message = result_state["messages"][-1].content
        
        if error:
            return AgentQueryResponse(
                success=False,
                intent=intent,
                generated_sql=sql_query,
                message=final_message,
                error=error,
                execution_time=execution_time
            )
            
        return AgentQueryResponse(
            success=True,
            intent=intent,
            generated_sql=sql_query,
            results=sql_results,
            result_count=len(sql_results) if sql_results else 0,
            execution_time=execution_time,
            message=final_message
        )
        
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        # Ensure context var is reset even on error
        # (Though in valid async flow with proper scope it might not matter, but good practice)
        # We can't easily reset 'token' here if it was set inside try. 
        # But ContextVars are thread/task local, so it clears on task end anyway? 
        # Actually no, in async it persists in the context. 
        # But this is a request handler, so the context is destroyed after response? 
        # Ideally use try/finally.
        
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
