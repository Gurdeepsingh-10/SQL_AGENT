from typing import Dict, Any, List
import contextvars
from langchain_core.messages import HumanMessage, AIMessage
from app.core.agent.state import AgentState
from app.core.agent.nlp_processor import NLPProcessor
from app.core.agent.sql_generator import SQLGenerator
from app.core.agent.validator import SQLValidator
from app.core.agent.executor import SQLExecutor
from app.core.agent.schema_inspector import SchemaInspector
from langchain_core.runnables import RunnableConfig

# ContextVar to hold the active DB engine for the current request
current_engine_cv = contextvars.ContextVar("current_engine", default=None)

# Stateless services can be global
nlp = NLPProcessor()
sql_gen = SQLGenerator()

def parse_intent(state: AgentState) -> Dict[str, Any]:
    """Node: Analyze natural language query for intent and entities."""
    query = state["query"]
    schema_context = state.get("schema_context", "")
    
    # Analyze intent
    intent_result = nlp.classify_intent(query, schema_context)
    intent = intent_result.get("intent", "UNKNOWN")
    
    # Extract entities
    entities = {}
    if intent != "UNKNOWN":
        entities = nlp.extract_entities(query, intent, schema_context)
    
    return {
        "intent": intent,
        "entities": entities,
        "messages": [AIMessage(content=f"Got it, looks like you want to {intent.lower().replace('_', ' ')}")]
    }

def generate_sql(state: AgentState) -> Dict[str, Any]:
    """Node: Generate SQL based on intent and entities."""
    query = state["query"]
    intent = state["intent"]
    entities = state["entities"]
    schema_context = state.get("schema_context", "")
    
    result = sql_gen.generate_sql(query, intent, entities, schema_context)
    sql_query = result.get("sql")
    
    if not sql_query:
        return {
            "error": result.get("error", "Failed to generate SQL"),
            "messages": [AIMessage(content="Hmm, I'm having trouble figuring out the right SQL for that request.")]
        }
        
    return {
        "sql_query": sql_query,
        "messages": [AIMessage(content=f"Generated SQL: {sql_query}")]
    }

def validate_sql(state: AgentState) -> Dict[str, Any]:
    """Node: Validate the generated SQL."""
    sql_query = state.get("sql_query")
    if not sql_query:
        return {"error": "No SQL to validate"}
    
    # Get current engine to perform schema-aware validation
    engine = current_engine_cv.get()
    if not engine:
        return {"error": "Database engine not available context"}
        
    inspector = SchemaInspector(engine)
    validator = SQLValidator(inspector)
        
    validation = validator.validate(sql_query)
    
    if not validation.get("is_valid", True) or not validation.get("is_safe", True):
        error_msg = validation.get("message", "Validation failed")
        return {
            "error": error_msg,
            "sql_query": None, # Clear invalid SQL
            "messages": [AIMessage(content=f"Hold on, there's an issue with the query: {error_msg}")]
        }

    # If valid, pass through
    return {}

def execute_sql(state: AgentState) -> Dict[str, Any]:
    """Node: Execute the SQL query."""
    sql_query = state.get("sql_query")
    
    if not sql_query:
        return {"error": "No SQL to execute"}
    
    # Get current engine
    engine = current_engine_cv.get()
    if not engine:
        return {"error": "Database engine not available in context"}
    
    executor = SQLExecutor(engine) 
    
    result = executor.execute_query(sql_query)
    
    if not result["success"]:
        return {
            "error": result.get("error"),
            "messages": [AIMessage(content=f"Ran into a problem: {result.get('error')}")]
        }
        
    return {
        "sql_results": result.get("data"),
        "sql_requires_confirmation": False, # Executed
        "messages": [AIMessage(content=executor.format_results_for_user(result))]
    }

def get_schema_info(state: AgentState) -> Dict[str, Any]:
    """Node: Get detailed information about the database schema."""
    engine = current_engine_cv.get()
    if not engine:
        return {"error": "Database engine not available"}
        
    inspector = SchemaInspector(engine)
    tables = inspector.get_all_tables()
    
    if not tables:
        return {
            "messages": [AIMessage(content="No tables found in the database.")],
        }
    
    # Build detailed schema information
    schema_details = []
    schema_details.append(f"Database contains {len(tables)} table(s):\n")
    
    for table in tables:
        table_schema = inspector.get_table_schema(table)
        columns = table_schema.get('columns', [])
        row_count = table_schema.get('row_count', 0)
        
        schema_details.append(f"\n**{table}** ({row_count} rows)")
        schema_details.append("Columns:")
        
        for col in columns:
            col_info = f"  - {col['name']}: {col['type']}"
            
            # Add constraints
            constraints = []
            if col.get('primary_key'):
                constraints.append('PK')
            if not col.get('nullable'):
                constraints.append('NOT NULL')
            if col.get('foreign_key'):
                constraints.append(f"FK -> {col['foreign_key']}")
            
            if constraints:
                col_info += f" [{', '.join(constraints)}]"
            
            schema_details.append(col_info)
    
    info = "\n".join(schema_details)
    
    return {
        "messages": [AIMessage(content=info)],
    }
