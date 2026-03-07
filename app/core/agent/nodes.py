"""
Agent Nodes — Production-Grade v2.
LangGraph node functions for the SQL agent pipeline.

Enhancements over v1:
- Structured CoT reasoning logged at every node
- Schema-grounded SQL generation (uses SchemaInspector.validate_references)
- Re-reasoning loop: if validation finds schema errors, re-generates SQL
  with correction hints (up to MAX_RE_REASONING_ATTEMPTS)
- Graceful degradation: every node returns a clear user message on failure
- Memory integration: reads from MemoryManager for context enrichment
- Context pruning: applies ContextPruner before adding new messages
- Dialect detection: passes dialect to SQLGenerator for dialect-specific SQL
"""

import contextvars
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, AIMessage

from app.core.agent.state import AgentState
from app.core.agent.nlp_processor import NLPProcessor
from app.core.agent.sql_generator import SQLGenerator
from app.core.agent.validator import SQLValidator
from app.core.agent.executor import SQLExecutor
from app.core.agent.schema_inspector import SchemaInspector, _get_dialect
from app.core.agent.memory_manager import memory_manager
from app.core.agent.context_pruner import context_pruner
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Context variable for the active DB engine (set per request)
# ---------------------------------------------------------------------------

current_engine_cv = contextvars.ContextVar("current_engine", default=None)

# ---------------------------------------------------------------------------
# Stateless services (global singletons)
# ---------------------------------------------------------------------------

nlp = NLPProcessor()
sql_gen = SQLGenerator()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RE_REASONING_ATTEMPTS = 2  # Max SQL re-generation attempts on schema errors

# ---------------------------------------------------------------------------
# Per-engine SchemaInspector + SQLValidator cache
# Avoids re-fetching the database schema on every validate_sql / execute_sql call.
# Keyed by id(engine) since engine objects are reused per connection.
# ---------------------------------------------------------------------------

_inspector_cache: Dict[int, SchemaInspector] = {}
_validator_cache: Dict[int, Any] = {}


def _get_cached_inspector(engine) -> SchemaInspector:
    """Return a cached SchemaInspector for the given engine, or create one."""
    key = id(engine)
    if key not in _inspector_cache:
        _inspector_cache[key] = SchemaInspector(engine)
        # Limit cache size (prevent memory leak after many connection changes)
        if len(_inspector_cache) > 50:
            oldest = next(iter(_inspector_cache))
            del _inspector_cache[oldest]
            if oldest in _validator_cache:
                del _validator_cache[oldest]
    return _inspector_cache[key]


def _get_cached_validator(engine) -> Any:
    """Return a cached SQLValidator for the given engine."""
    from app.core.agent.validator import SQLValidator as _SQLValidator
    key = id(engine)
    if key not in _validator_cache:
        inspector = _get_cached_inspector(engine)
        _validator_cache[key] = _SQLValidator(inspector)
    return _validator_cache[key]


# ---------------------------------------------------------------------------
# Helper: extract conversation history for NLP context
# ---------------------------------------------------------------------------

def _extract_history(messages: List[Any]) -> List[Dict[str, str]]:
    """Convert LangChain messages to simple dicts for NLP processor."""
    history = []
    for msg in messages[-8:]:  # Last 8 messages for coreference context
        if hasattr(msg, "content") and msg.content:
            role = "assistant" if hasattr(msg, "type") and msg.type == "ai" else "user"
            history.append({"role": role, "content": str(msg.content)[:500]})
    return history


def _get_last_sql_from_history(messages: List[Any]) -> Optional[str]:
    """Extract the most recently executed SQL from message history.

    This is used to give the SQL generator context about the previous operation
    when handling follow-up queries like 'show me the rows that were affected'.
    We scan backwards through messages looking for content that starts with a SQL keyword.
    """
    sql_keywords = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")
    for msg in reversed(messages):
        content = ""
        if hasattr(msg, "content"):
            content = str(msg.content)
        elif isinstance(msg, dict):
            content = str(msg.get("content", ""))
        # Check if any line looks like SQL
        for line in content.strip().splitlines():
            stripped = line.strip().upper()
            if any(stripped.startswith(kw) for kw in sql_keywords):
                return content.strip()[:600]
    return None


# ---------------------------------------------------------------------------
# Node: parse_intent
# ---------------------------------------------------------------------------

def parse_intent(state: AgentState) -> Dict[str, Any]:
    """
    Node: Analyze natural language query for intent, entities, and CoT reasoning.

    CRITICAL: This node MUST reset all per-turn SQL pipeline fields.
    LangGraph MemorySaver restores the full previous checkpoint, so stale
    sql_query / sql_results / intent / error from the last turn will persist
    unless explicitly cleared here.
    """
    query = state["query"]
    schema_context = state.get("schema_context", "")
    messages = state.get("messages", [])

    # Prune messages if needed before adding new ones
    if context_pruner.should_summarize(messages):
        messages, summary = context_pruner.summarize_history(messages, schema_context)
        if summary:
            logger.info("[parse_intent] Summarized conversation history")

    # Build conversation history for coreference resolution
    # IMPORTANT: only use AI/human message content, NOT sql_query from state
    history = _extract_history(messages)

    # Classify intent with CoT
    intent_result = nlp.classify_intent(query, schema_context, history)

    intent = intent_result.get("intent", "UNKNOWN")
    confidence = float(intent_result.get("confidence", 0.0))
    entities = intent_result.get("entities", {})
    reasoning = intent_result.get("reasoning", "")
    sub_tasks = intent_result.get("sub_tasks", [])
    resolved_query = intent_result.get("resolved_query", query)

    logger.info(
        f"[parse_intent] intent={intent} confidence={confidence:.2f} "
        f"sub_tasks={len(sub_tasks)} resolved='{resolved_query[:60]}'"
    )

    # CRITICAL: Reset ALL per-turn mutable fields to prevent stale state bleed-through.
    # The MemorySaver checkpoint restores the previous turn's sql_query, sql_results,
    # error, etc. We must explicitly overwrite them here so the new turn starts clean.
    return {
        # Intent classification results
        "intent": intent,
        "intent_confidence": confidence,
        "entities": entities,
        "reasoning": reasoning,
        "sub_tasks": sub_tasks,
        "resolved_query": resolved_query,

        # Reset SQL pipeline — MUST be cleared to prevent last turn's SQL from re-executing
        "sql_query": None,
        "sql_results": None,
        "sql_requires_confirmation": False,

        # Reset validation state
        "re_reasoning_attempts": 0,
        "requires_re_reasoning": False,
        "schema_errors": {},

        # Reset error state
        "error": None,
        "execution_error_type": None,

        # Conversation message
        "messages": [
            AIMessage(
                content=(
                    f"Understood. This looks like a {intent.lower().replace('_', ' ')} request"
                    + (f" (confidence: {confidence:.0%})" if confidence < 0.9 else "")
                    + (f"\nReasoning: {reasoning[:200]}" if reasoning else "")
                )
            )
        ],
    }


# ---------------------------------------------------------------------------
# Node: generate_sql
# ---------------------------------------------------------------------------

def generate_sql(state: AgentState) -> Dict[str, Any]:
    """
    Node: Generate SQL using multi-pass refinement with schema grounding.

    Enhancements:
    - Uses resolved_query (after coreference resolution)
    - Passes CoT reasoning to SQLGenerator for context
    - Detects database dialect for dialect-specific SQL
    - Passes memory context (similar past patterns) to generator
    """
    query = state.get("resolved_query") or state["query"]
    intent = state["intent"]
    entities = state.get("entities", {})
    schema_context = state.get("schema_context", "")
    reasoning = state.get("reasoning", "")
    re_attempt = state.get("re_reasoning_attempts", 0)
    schema_errors = state.get("schema_errors", {})

    # Detect dialect from engine
    engine = current_engine_cv.get()
    dialect = "sqlite"
    if engine:
        try:
            dialect = _get_dialect(engine)
        except Exception:
            pass

    # Determine if we should prune the schema context to save tokens and improve speed.
    # We use the tables identified in the intent parsing phase.
    relevant_tables = entities.get("tables", [])
    if relevant_tables and engine:
        try:
            inspector = _get_cached_inspector(engine)
            # This returns a pruned schema context including only identified tables + neighbors
            schema_context = inspector.get_schema_context_for_llm(relevant_tables)
            logger.info(
                f"[generate_sql] Using pruned schema context "
                f"({len(relevant_tables)} tables + neighbors)"
            )
        except Exception as e:
            logger.warning(f"[generate_sql] Schema pruning failed, falling back to full: {e}")

    # If this is a re-reasoning attempt, enrich the query with correction hints
    correction_hint = ""
    if re_attempt > 0 and schema_errors:
        missing_tables = schema_errors.get("missing_tables", [])
        missing_cols = schema_errors.get("missing_columns", {})
        suggestions = schema_errors.get("suggestions", {})

        hints = []
        for t in missing_tables:
            sugg = suggestions.get(t, [])
            if sugg:
                hints.append(f"Table '{t}' does not exist. Use '{sugg[0]}' instead.")
        for table, cols in missing_cols.items():
            for c in cols:
                sugg = suggestions.get(c, [])
                if sugg:
                    hints.append(
                        f"Column '{c}' does not exist in '{table}'. "
                        f"Use '{sugg[0]}' instead."
                    )

        if hints:
            correction_hint = (
                f"\n\nCORRECTION REQUIRED (attempt {re_attempt + 1}):\n"
                + "\n".join(f"- {h}" for h in hints)
            )
            query = query + correction_hint

    logger.info(
        f"[generate_sql] Generating SQL (dialect={dialect}, "
        f"re_attempt={re_attempt}, intent={intent})"
    )

    result = sql_gen.generate_sql(
        query=query,
        intent=intent,
        entities=entities,
        schema_context=schema_context,
        dialect=dialect,
        reasoning=reasoning,
        last_sql_context=_get_last_sql_from_history(state.get("messages", [])),
    )

    sql_query = result.get("sql")

    if not sql_query:
        error_msg = result.get("error", "Failed to generate SQL")
        logger.error(f"[generate_sql] SQL generation failed: {error_msg}")
        return {
            "error": error_msg,
            "dialect": dialect,
            "messages": [
                AIMessage(
                    content=(
                        "I'm having trouble generating the right SQL for that request. "
                        f"Error: {error_msg}"
                    )
                )
            ],
        }

    return {
        "sql_query": sql_query,
        "chart_config": result.get("chart_config"),
        "dialect": dialect,
        "requires_re_reasoning": False,
        "schema_errors": {},
        "messages": [
            AIMessage(
                content=f"Generated SQL ({dialect.upper()}):\n```sql\n{sql_query}\n```"
            )
        ],
    }


# ---------------------------------------------------------------------------
# Node: validate_sql
# ---------------------------------------------------------------------------

def validate_sql(state: AgentState) -> Dict[str, Any]:
    """
    Node: Validate generated SQL with strict schema cross-checking.

    Enhancements:
    - Uses SchemaInspector.validate_references() for strict grounding
    - Returns requires_re_reasoning=True if schema errors found
    - Provides structured schema_errors with suggestions for re-generation
    - Checks NULL comparisons and GROUP BY completeness
    """
    sql_query = state.get("sql_query")
    if not sql_query:
        return {"error": "No SQL to validate"}

    engine = current_engine_cv.get()
    if not engine:
        return {"error": "Database engine not available in context"}

    # Use cached inspector + validator — avoids DB schema re-fetch on every call
    validator = _get_cached_validator(engine)

    validation = validator.validate(sql_query, state.get("intent"))

    is_valid = validation.get("is_valid", True)
    is_safe = validation.get("is_safe", True)
    errors = validation.get("errors", [])
    warnings = validation.get("warnings", [])
    schema_errors = validation.get("schema_errors", {})
    requires_re_reasoning = validation.get("requires_re_reasoning", False)

    # Log warnings
    if warnings:
        logger.warning(f"[validate_sql] Warnings: {'; '.join(warnings)}")

    if not is_valid or not is_safe:
        error_msg = "; ".join(errors) if errors else "Validation failed"

        if requires_re_reasoning:
            re_attempt = state.get("re_reasoning_attempts", 0)
            logger.info(
                f"[validate_sql] Schema errors detected, triggering re-reasoning "
                f"(attempt {re_attempt + 1}/{MAX_RE_REASONING_ATTEMPTS})"
            )
            return {
                "error": None,  # Don't set error — allow re-reasoning
                "sql_query": None,
                "schema_errors": schema_errors,
                "requires_re_reasoning": True,
                "re_reasoning_attempts": re_attempt + 1,
                "messages": [
                    AIMessage(
                        content=(
                            f"The generated SQL references objects that don't exist in the schema. "
                            f"Re-generating with corrections... ({re_attempt + 1}/{MAX_RE_REASONING_ATTEMPTS})"
                        )
                    )
                ],
            }

        # Non-schema validation failure (injection, permissions, etc.)
        return {
            "error": error_msg,
            "sql_query": None,
            "messages": [
                AIMessage(
                    content=error_msg
                )
            ],
        }

    # Valid — pass through with sanitized SQL
    sanitized = validation.get("sanitized_sql", sql_query)
    return {
        "sql_query": sanitized,
        "requires_re_reasoning": False,
        "schema_errors": {},
    }


# ---------------------------------------------------------------------------
# Node: execute_sql
# ---------------------------------------------------------------------------

def execute_sql(state: AgentState) -> Dict[str, Any]:
    """
    Node: Execute the validated SQL query with retry logic.

    Enhancements:
    - Uses upgraded SQLExecutor with retry and error classification
    - Records successful queries in MemoryManager
    - Invalidates schema cache after DDL operations (schema changed)
    - Returns structured error_type for downstream handling
    """
    sql_query = state.get("sql_query")
    if not sql_query:
        return {"error": "No SQL to execute"}

    engine = current_engine_cv.get()
    if not engine:
        return {"error": "Database engine not available in context"}

    # Reuse executor (stateless — safe to cache per engine)
    executor = SQLExecutor(engine)
    result = executor.execute_query(sql_query)

    if not result["success"]:
        error_type = result.get("error_type", "permanent")
        error_msg = result.get("error", "Execution failed")

        logger.error(
            f"[execute_sql] Execution failed (type={error_type}): {error_msg[:200]}"
        )

        return {
            "error": error_msg,
            "execution_error_type": error_type,
            "messages": [
                AIMessage(
                    content=executor.format_results_for_user(result)
                )
            ],
        }

    # Success
    intent = state.get("intent", "QUERY")
    connection_id = state.get("db_connection_id")

    # After DML (INSERT/UPDATE/DELETE), force the schema inspector to
    # re-count rows. This ensures the schema display shows accurate row counts
    # instead of stale '0 rows' after inserts.
    if intent in ("DDL", "INSERT", "UPDATE", "DELETE"):
        if connection_id:
            memory_manager.invalidate_schema_snapshot(connection_id)
        if engine:
            key = id(engine)
            if key in _inspector_cache:
                # Only clear the internal row count cache, not the full schema
                # (DDL also clears column structure)
                if intent == "DDL":
                    _inspector_cache[key].clear_cache()
                    del _inspector_cache[key]
                    if key in _validator_cache:
                        del _validator_cache[key]
                else:
                    # Use the dedicated method that busts all cache layers
                    # (TTL + fingerprint) so the next schema request returns
                    # accurate row counts after DML.
                    _inspector_cache[key].clear_row_count_cache()
                logger.info(f"[execute_sql] {intent} — schema cache busted, row counts will refresh")

    # Record successful pattern in long-term memory
    if connection_id:
        memory_manager.record_successful_pattern(
            user_id=0,  # Will be enriched in route handler
            query=state.get("resolved_query") or state["query"],
            sql=sql_query,
            intent=intent,
        )

    return {
        "sql_results": result.get("data"),
        "sql_requires_confirmation": False,
        "execution_error_type": None,
        "messages": [
            AIMessage(content=executor.format_results_for_user(result))
        ],
    }


# ---------------------------------------------------------------------------
# Node: get_schema_info
# ---------------------------------------------------------------------------

def get_schema_info(state: AgentState) -> Dict[str, Any]:
    """
    Node: Return detailed schema information to the user.
    Uses the shared cached inspector — schema is already in memory from
    the agent.py route handler, so get_full_schema() returns immediately
    from the TTL cache with zero DB queries.
    """
    engine = current_engine_cv.get()
    if not engine:
        return {"error": "Database engine not available"}

    # Reuse the cached inspector — avoids a second full schema rebuild
    inspector = _get_cached_inspector(engine)
    schema = inspector.get_full_schema()
    tables = list(schema["tables"].keys())

    if not tables:
        return {
            "messages": [
                AIMessage(content="The database is empty — no tables found.")
            ],
        }

    lines = [f"Database contains {len(tables)} table(s):\n"]

    for table_name, tinfo in schema["tables"].items():
        row_count = tinfo.get("row_count", 0)
        lines.append(f"\n**{table_name}** ({row_count} rows)")
        lines.append("Columns:")

        for col in tinfo.get("columns", []):
            col_info = f"  - {col['name']}: {col['type']}"
            flags = []
            if col.get("primary_key"):
                flags.append("PK")
            if not col.get("nullable"):
                flags.append("NOT NULL")
            if col.get("foreign_key"):
                flags.append(f"FK→{col['foreign_key']}")
            if flags:
                col_info += f" [{', '.join(flags)}]"
            lines.append(col_info)

        # FK relationships
        fk_rels = inspector._fk_graph.get(table_name, [])
        if fk_rels:
            lines.append("Relationships:")
            for rel in fk_rels:
                lines.append(
                    f"  {table_name}.{rel['from_col']} → "
                    f"{rel['to_table']}.{rel['to_col']}"
                )

        indexed = tinfo.get("indexed_columns", [])
        if indexed:
            lines.append(f"Indexed columns: {', '.join(indexed)}")

    info = "\n".join(lines)

    # Cache schema in memory manager
    connection_id = state.get("db_connection_id")
    if connection_id:
        memory_manager.store_schema_snapshot(
            connection_id=connection_id,
            schema_context=inspector.get_schema_context_for_llm(),
            fingerprint=inspector._schema_fingerprint or "",
            table_count=len(tables),
        )

    return {
        "messages": [AIMessage(content=info)],
    }


# ---------------------------------------------------------------------------
# Node: clarify_query
# ---------------------------------------------------------------------------

def clarify_query(state: AgentState) -> Dict[str, Any]:
    """
    Node: Ask the user to clarify an ambiguous request.

    Enhancements:
    - Uses schema context to suggest specific table/column names
    - Provides structured clarification questions
    - Includes confidence score in response
    """
    intent = state.get("intent", "UNKNOWN")
    entities = state.get("entities", {})
    query = state.get("resolved_query") or state.get("query", "")
    confidence = state.get("intent_confidence", 0.0)
    schema_context = state.get("schema_context", "")

    hints = []

    tables = entities.get("tables") if isinstance(entities, dict) else None
    columns = entities.get("columns") if isinstance(entities, dict) else None
    conditions = entities.get("conditions") if isinstance(entities, dict) else None

    if not tables:
        # Extract available tables from schema context for suggestions
        available_tables = []
        for line in schema_context.splitlines():
            if line.startswith("TABLE:"):
                table_name = line.split("TABLE:")[1].split("(")[0].strip()
                available_tables.append(table_name)

        if available_tables:
            hints.append(
                f"Which table should I use? Available: {', '.join(available_tables[:5])}"
            )
        else:
            hints.append("Which table(s) should I use?")

    if intent in ["INSERT", "UPDATE"] and not columns:
        hints.append("Which columns and values are involved?")

    if intent in ["QUERY", "UPDATE", "DELETE"] and not conditions:
        hints.append("Do you have any filters or specific criteria?")

    if confidence < 0.4:
        hints.append(
            f"Your request is ambiguous (confidence: {confidence:.0%}). "
            "Could you rephrase it more specifically?"
        )

    if not hints:
        hints.append("Could you provide more detail so I can be precise?")

    clarification = (
        "Your request needs clarification:\n- " + "\n- ".join(hints)
    )

    return {
        "error": "AMBIGUOUS_REQUEST",
        "messages": [
            AIMessage(content=clarification),
            HumanMessage(content=query),
        ],
    }
