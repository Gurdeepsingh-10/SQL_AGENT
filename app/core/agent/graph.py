from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from app.core.agent.state import AgentState
from app.core.agent.nodes import parse_intent, generate_sql, validate_sql, execute_sql, get_schema_info

# Define the graph
workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("parse_intent", parse_intent)
workflow.add_node("generate_sql", generate_sql)
workflow.add_node("validate_sql", validate_sql)
workflow.add_node("execute_sql", execute_sql)
workflow.add_node("get_schema_info", get_schema_info)

# Define edges
workflow.set_entry_point("parse_intent")

def should_generate_sql(state: AgentState):
    """Conditional edge: Determine if we should generate SQL."""
    intent = state.get("intent")
    if intent == "SCHEMA_INFO":
        return "get_schema_info"
    if intent in ["QUERY", "INSERT", "UPDATE", "DELETE", "DDL"]:
        return "generate_sql"
    return END

def should_execute_sql(state: AgentState):
    """Conditional edge: Determine if we should execute SQL."""
    if state.get("error"):
        return END
    return "execute_sql"

def should_validate_sql(state: AgentState):
    """Conditional edge: Check if SQL was generated."""
    if state.get("error"):
        return END
    if state.get("sql_query"):
        return "validate_sql"
    return END

workflow.add_conditional_edges(
    "parse_intent",
    should_generate_sql,
    {
        "generate_sql": "generate_sql",
        "get_schema_info": "get_schema_info",
        END: END
    }
)

workflow.add_edge("get_schema_info", END)

workflow.add_conditional_edges(
    "generate_sql",
    should_validate_sql,
    {
        "validate_sql": "validate_sql",
        END: END
    }
)

workflow.add_conditional_edges(
    "validate_sql",
    should_execute_sql,
    {
        "execute_sql": "execute_sql",
        END: END
    }
)

workflow.add_edge("execute_sql", END)

# Compile with memory for chat history (optional for now)
graph = workflow.compile(checkpointer=MemorySaver())
