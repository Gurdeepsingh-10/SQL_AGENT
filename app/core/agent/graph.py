"""
LangGraph Agent Graph — Production-Grade v2.

Enhancements over v1:
- Loop detection: re-reasoning cycle is bounded by MAX_RE_REASONING_ATTEMPTS
- Fallback escalation: if max re-reasoning attempts exceeded, returns graceful error
- Conditional routing handles the new requires_re_reasoning flag
- SessionManager extended with two-tier memory integration
- Graph compiled with MemorySaver for conversation persistence
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.core.agent.state import AgentState
from app.core.agent.nodes import (
    parse_intent,
    generate_sql,
    validate_sql,
    execute_sql,
    get_schema_info,
    clarify_query,
    MAX_RE_REASONING_ATTEMPTS,
)
from app.core.agent.memory_manager import memory_manager

# ---------------------------------------------------------------------------
# Build the StateGraph
# ---------------------------------------------------------------------------

workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("parse_intent", parse_intent)
workflow.add_node("generate_sql", generate_sql)
workflow.add_node("validate_sql", validate_sql)
workflow.add_node("execute_sql", execute_sql)
workflow.add_node("get_schema_info", get_schema_info)
workflow.add_node("clarify_query", clarify_query)

# Entry point
workflow.set_entry_point("parse_intent")


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------

def route_after_parse_intent(state: AgentState) -> str:
    """
    Route after intent classification.
    - SCHEMA_INFO → get_schema_info
    - UNKNOWN or low confidence → clarify_query
    - QUERY/INSERT/UPDATE/DELETE/DDL → generate_sql
    - Error → END
    """
    if state.get("error"):
        return END

    intent = state.get("intent", "UNKNOWN")
    confidence = state.get("intent_confidence", 0.0)

    if intent == "SCHEMA_INFO":
        return "get_schema_info"

    if intent == "UNKNOWN" or confidence < 0.6:
        return "clarify_query"

    if intent in {"QUERY", "INSERT", "UPDATE", "DELETE", "DDL"}:
        return "generate_sql"

    return END


def route_after_generate_sql(state: AgentState) -> str:
    """
    Route after SQL generation.
    - Error → END
    - SQL generated → validate_sql
    """
    if state.get("error"):
        return END
    if state.get("sql_query"):
        return "validate_sql"
    return END


def route_after_validate_sql(state: AgentState) -> str:
    """
    Route after SQL validation.
    - Hard error (injection, permissions) → END
    - Schema errors + re-reasoning allowed → generate_sql (re-reasoning loop)
    - Schema errors + max attempts exceeded → END (graceful degradation)
    - Valid → execute_sql
    """
    if state.get("error"):
        return END

    requires_re_reasoning = state.get("requires_re_reasoning", False)
    re_attempts = state.get("re_reasoning_attempts", 0)

    if requires_re_reasoning:
        if re_attempts <= MAX_RE_REASONING_ATTEMPTS:
            # Re-enter generate_sql with correction hints
            return "generate_sql"
        else:
            # Max attempts exceeded — graceful degradation
            return END

    if state.get("sql_query"):
        return "execute_sql"

    return END


# ---------------------------------------------------------------------------
# Wire edges
# ---------------------------------------------------------------------------

workflow.add_conditional_edges(
    "parse_intent",
    route_after_parse_intent,
    {
        "generate_sql": "generate_sql",
        "get_schema_info": "get_schema_info",
        "clarify_query": "clarify_query",
        END: END,
    },
)

workflow.add_edge("get_schema_info", END)
workflow.add_edge("clarify_query", END)

workflow.add_conditional_edges(
    "generate_sql",
    route_after_generate_sql,
    {
        "validate_sql": "validate_sql",
        END: END,
    },
)

workflow.add_conditional_edges(
    "validate_sql",
    route_after_validate_sql,
    {
        "generate_sql": "generate_sql",  # Re-reasoning loop
        "execute_sql": "execute_sql",
        END: END,
    },
)

workflow.add_edge("execute_sql", END)

# ---------------------------------------------------------------------------
# Compile with MemorySaver for conversation persistence
# ---------------------------------------------------------------------------

graph = workflow.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Session Manager — extended with two-tier memory integration
# ---------------------------------------------------------------------------

class SessionManager:
    """
    Manages per-user, per-connection conversation sessions.

    Thread IDs are deterministic: {user_id}_{connection_id}_{nonce}
    Advancing the nonce starts a fresh LangGraph thread while preserving
    long-term memory in MemoryManager.
    """

    def __init__(self):
        self._nonces: dict = {}  # (user_id, connection_id) -> int

    def get_nonce(self, user_id: int, connection_id: int) -> int:
        return self._nonces.get((user_id, connection_id), 0)

    def reset_nonce(self, user_id: int, connection_id: int) -> int:
        """
        Advance the nonce to start a fresh conversation thread.
        Also clears the old session from MemoryManager.
        """
        key = (user_id, connection_id)
        old_nonce = self._nonces.get(key, 0)
        new_nonce = old_nonce + 1
        self._nonces[key] = new_nonce

        # Clear old session from memory manager
        old_thread_id = f"{user_id}_{connection_id}_{old_nonce}"
        memory_manager.clear_session(old_thread_id)

        return new_nonce

    def status_for_user(self, user_id: int) -> dict:
        return {
            conn_id: nonce
            for (u_id, conn_id), nonce in self._nonces.items()
            if u_id == user_id
        }


_session_manager = SessionManager()


def get_thread_id(user_id: int, connection_id: int) -> str:
    """Get the current thread ID for a user+connection pair."""
    return f"{user_id}_{connection_id}_{_session_manager.get_nonce(user_id, connection_id)}"


def reset_session(user_id: int, connection_id: int) -> int:
    """Reset conversation memory for a user+connection pair."""
    return _session_manager.reset_nonce(user_id, connection_id)


def get_user_session_status(user_id: int) -> dict:
    """Get session nonce status for all of a user's connections."""
    return _session_manager.status_for_user(user_id)
