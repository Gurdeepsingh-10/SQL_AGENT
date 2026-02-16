from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    query: str
    intent: str
    entities: Dict[str, Any]
    sql_query: Optional[str]
    sql_results: Optional[List[Dict[str, Any]]]
    sql_requires_confirmation: bool
    error: Optional[str]
    messages: Annotated[List[Any], add_messages]
    db_connection_id: Optional[int]
    schema_context: str
