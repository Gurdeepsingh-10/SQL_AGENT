"""
Agent State — Extended for production-grade pipeline.

New fields:
- intent_confidence: float for confidence-gated routing
- reasoning: CoT reasoning from NLP processor
- sub_tasks: multi-intent decomposition
- resolved_query: coreference-resolved query
- schema_errors: structured schema validation errors
- requires_re_reasoning: flag to trigger SQL re-generation
- re_reasoning_attempts: loop detection counter
- dialect: database dialect for SQL generation
- memory_context: assembled memory context string
- execution_error_type: error classification from executor
"""

from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # Core query fields
    query: str
    resolved_query: str                    # After coreference resolution
    intent: str
    intent_confidence: float               # 0.0 - 1.0
    entities: Dict[str, Any]
    reasoning: str                         # CoT reasoning steps

    # Multi-intent support
    sub_tasks: List[Dict[str, Any]]        # Ordered sub-tasks for compound queries

    # SQL generation
    sql_query: Optional[str]
    chart_config: Optional[Dict[str, Any]] # Chart.js config from LLM
    dialect: str                           # postgresql / mysql / sqlite / mssql / oracle

    # Validation
    schema_errors: Dict[str, Any]          # Missing tables/columns with suggestions
    requires_re_reasoning: bool            # Trigger SQL re-generation
    re_reasoning_attempts: int             # Loop detection counter

    # Execution
    sql_results: Optional[List[Dict[str, Any]]]
    sql_requires_confirmation: bool
    confirmed: bool                            # Set True by frontend after user approves modal
    execution_error_type: Optional[str]    # transient / schema / permission / permanent

    # Error handling
    error: Optional[str]

    # Conversation
    messages: Annotated[List[Any], add_messages]
    memory_context: str                    # Assembled from MemoryManager

    # Context
    db_connection_id: Optional[int]
    schema_context: str
