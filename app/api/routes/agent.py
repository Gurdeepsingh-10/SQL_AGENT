"""
SQL Agent routes for natural language query processing.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse, QueryHistoryResponse, QueryHistoryItem
from app.models.user import User
from app.models.query_history import QueryHistory
from app.api.deps import get_current_user
from app.core.agent.schema_inspector import SchemaInspector
from app.core.agent.graph import graph, get_thread_id, reset_session, get_user_session_status
from app.core.agent.nodes import current_engine_cv, _get_cached_inspector
from app.utils.logger import get_logger
import time

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["SQL Agent"])

# Note: NLPProcessor, SQLGenerator, SchemaInspector, SQLValidator, SQLExecutor
# are instantiated as global singletons in nodes.py and reused across all requests.


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
    
    token = None
    try:
        # Set the current engine for the request context (used by graph nodes)
        token = current_engine_cv.set(target_engine)

        # Get schema context — check memory cache first
        from app.core.agent.memory_manager import memory_manager
        connection_id = target_connection.id if target_connection else None

        cached_snapshot = memory_manager.get_schema_snapshot(connection_id) if connection_id else None
        if cached_snapshot:
            schema_context = cached_snapshot.schema_context
            logger.info(f"Using cached schema snapshot for connection {connection_id}")
        else:
            # Use cached inspector — same object reused by validate_sql, avoids double schema fetch
            schema_inspector = _get_cached_inspector(target_engine)
            schema_context = schema_inspector.get_schema_context_for_llm()
            # Cache it in memory manager for future requests
            if connection_id:
                memory_manager.store_schema_snapshot(
                    connection_id=connection_id,
                    schema_context=schema_context,
                    fingerprint=schema_inspector._schema_fingerprint or "",
                    table_count=schema_inspector.get_full_schema().get("total_tables", 0),
                )

        # Get or create session memory
        thread_id = get_thread_id(current_user.id, target_connection.id)
        session = memory_manager.get_or_create_session(
            user_id=current_user.id,
            connection_id=target_connection.id,
            thread_id=thread_id,
        )

        # Build memory context for the agent
        mem_context = memory_manager.build_memory_context(
            user_id=current_user.id,
            thread_id=thread_id,
        )

        # Prepare graph inputs — CRITICAL: explicitly reset ALL per-turn mutable fields.
        # LangGraph MemorySaver restores the full previous checkpoint state.
        # Any field not explicitly set here will retain its value from the last turn,
        # causing stale sql_query / intent / error to bleed into the new request.
        inputs = {
            # New query
            "query": query_text,
            "resolved_query": query_text,

            # Context (fresh each turn)
            "schema_context": schema_context,
            "db_connection_id": connection_id,
            "memory_context": mem_context,

            # Reset ALL per-turn output fields to clean state
            "intent": "",
            "intent_confidence": 0.0,
            "entities": {},
            "reasoning": "",
            "sub_tasks": [],
            "dialect": "sqlite",

            # Reset SQL pipeline fields
            "sql_query": None,
            "sql_results": None,
            "sql_requires_confirmation": False,

            # Reset validation fields
            "schema_errors": {},
            "requires_re_reasoning": False,
            "re_reasoning_attempts": 0,

            # Reset error fields
            "error": None,
            "execution_error_type": None,
        }

        # Invoke LangGraph
        result_state = await graph.ainvoke(
            inputs,
            config={"configurable": {"thread_id": thread_id}}
        )

        # Process results
        execution_time = time.time() - start_time

        intent = result_state.get("intent", "UNKNOWN")
        error = result_state.get("error")
        sql_query = result_state.get("sql_query")
        sql_results = result_state.get("sql_results")

        # Record in session memory
        memory_manager.record_query_in_session(
            thread_id=thread_id,
            query=query_text,
            intent=intent,
            sql=sql_query,
            success=error is None,
            result_count=len(sql_results) if sql_results else 0,
            error=error if error != "AMBIGUOUS_REQUEST" else None,
        )

        # Record successful patterns in long-term memory
        if not error and sql_query:
            memory_manager.record_successful_pattern(
                user_id=current_user.id,
                query=query_text,
                sql=sql_query,
                intent=intent,
            )

        # Invalidate schema cache after DDL operations (belt-and-suspenders)
        # The execute_sql node also does this, but we do it here too to ensure
        # the route-level cache is always fresh after schema changes.
        if intent == "DDL" and not error and connection_id:
            memory_manager.invalidate_schema_snapshot(connection_id)
            logger.info(f"Route: invalidated schema cache after DDL for connection {connection_id}")

        # Populate history
        history.intent = intent
        history.generated_sql = sql_query
        history.success = error is None or error == "AMBIGUOUS_REQUEST"
        history.error_message = error if error != "AMBIGUOUS_REQUEST" else None
        history.execution_time = execution_time
        history.result_count = len(sql_results) if sql_results else 0

        db.add(history)
        db.commit()

        # Determine final message
        final_message = "Query executed successfully"
        if result_state.get("messages"):
            last_msg = result_state["messages"][-1]
            final_message = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

        if error and error != "AMBIGUOUS_REQUEST":
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
            chart_config=result_state.get("chart_config"),
            result_count=len(sql_results) if sql_results else 0,
            execution_time=execution_time,
            message=final_message
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
    finally:
        # Always reset the context variable
        if token is not None:
            current_engine_cv.reset(token)


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


@router.post("/memory/reset")
async def reset_memory_for_connection(
    connection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Reset conversation memory for the given connection by advancing the session nonce.
    """
    from app.models.user_connection import UserConnection
    
    connection = db.query(UserConnection).filter(
        UserConnection.id == connection_id,
        UserConnection.user_id == current_user.id
    ).first()
    
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found"
        )
    
    new_nonce = reset_session(current_user.id, connection_id)
    return {
        "success": True,
        "message": "Conversation memory reset",
        "connection_id": connection_id,
        "session_nonce": new_nonce,
        "thread_id": get_thread_id(current_user.id, connection_id)
    }


@router.get("/memory/status")
async def memory_status(
    current_user: User = Depends(get_current_user)
):
    """
    Get session nonce status for all of the user's connections.
    """
    status_map = get_user_session_status(current_user.id)
    return {
        "success": True,
        "sessions": status_map
    }


@router.get("/cache/stats")
async def cache_stats(
    current_user: User = Depends(get_current_user)
):
    """
    Return in-memory cache statistics for NLP intent classification and SQL generation.
    Useful for monitoring cache effectiveness and latency optimisation impact.
    """
    from app.core.agent.nlp_processor import (
        _INTENT_CACHE, _CACHE_HITS, _CACHE_MISSES, _INTENT_CACHE_MAX
    )
    from app.core.agent.sql_generator import _SQL_CACHE, _SQL_CACHE_MAX
    from app.core.agent.nodes import _inspector_cache, _validator_cache

    total_nlp = _CACHE_HITS + _CACHE_MISSES
    hit_rate = round(_CACHE_HITS / total_nlp * 100, 1) if total_nlp > 0 else 0.0

    return {
        "success": True,
        "intent_cache": {
            "size": len(_INTENT_CACHE),
            "max": _INTENT_CACHE_MAX,
            "hits": _CACHE_HITS,
            "misses": _CACHE_MISSES,
            "hit_rate_pct": hit_rate,
        },
        "sql_cache": {
            "size": len(_SQL_CACHE),
            "max": _SQL_CACHE_MAX,
        },
        "inspector_cache": {
            "engines_cached": len(_inspector_cache),
        },
    }
