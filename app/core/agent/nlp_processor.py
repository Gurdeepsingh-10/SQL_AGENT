"""
NLP Processor — Production-Grade v2.
Processes natural language queries to extract intent, entities, and reasoning.

Enhancements over v1:
- Chain-of-thought (CoT) enforcement: LLM must output explicit reasoning steps
- Multi-intent decomposition: splits compound queries into ordered sub-tasks
- Coreference / pronoun resolution using conversation history
- Confidence-gated fallback: low-confidence results trigger clarification
- Structured entity extraction with FK-aware table/column resolution
- Retry logic with exponential backoff on Groq API failures
"""

from groq import Groq
from typing import Dict, Any, List, Optional
from app.config import settings
from app.utils.logger import get_logger
import json
import time
import re

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTENT_QUERY = "QUERY"
INTENT_INSERT = "INSERT"
INTENT_UPDATE = "UPDATE"
INTENT_DELETE = "DELETE"
INTENT_DDL = "DDL"
INTENT_SCHEMA_INFO = "SCHEMA_INFO"
INTENT_UNKNOWN = "UNKNOWN"

VALID_INTENTS = {
    INTENT_QUERY, INTENT_INSERT, INTENT_UPDATE,
    INTENT_DELETE, INTENT_DDL, INTENT_SCHEMA_INFO, INTENT_UNKNOWN,
}

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extract the first JSON object from an LLM response.
    Handles markdown code fences and leading/trailing prose.
    """
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)

    # Find first { ... } block
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _call_groq_with_retry(
    client: Groq,
    model: str,
    messages: List[Any],
    temperature: float = 0.1,
    max_tokens: int = 800,
) -> Optional[str]:
    """
    Call Groq API with exponential backoff retry on transient failures.
    Returns the response text or None on permanent failure.
    """
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            return content.strip() if content is not None else None
        except Exception as e:
            err_str = str(e).lower()
            is_transient = any(
                kw in err_str
                for kw in ("rate_limit", "timeout", "503", "502", "connection")
            )
            if is_transient and attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"[NLPProcessor] Groq transient error (attempt {attempt+1}): {e}. "
                    f"Retrying in {delay:.1f}s"
                )
                time.sleep(delay)
            else:
                logger.error(f"[NLPProcessor] Groq permanent error: {e}")
                return None
    return None


# ---------------------------------------------------------------------------
# NLPProcessor
# ---------------------------------------------------------------------------

class NLPProcessor:
    """
    Processes natural language queries with chain-of-thought reasoning,
    multi-intent decomposition, and coreference resolution.
    """

    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL

    # ------------------------------------------------------------------
    # Primary: classify intent with CoT
    # ------------------------------------------------------------------

    def classify_intent(
        self,
        query: str,
        schema_context: str = "",
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Classify intent with explicit chain-of-thought reasoning.

        Returns:
            {
                "intent": str,
                "confidence": float,
                "entities": {...},
                "reasoning": str,          # CoT steps
                "sub_tasks": [...],        # For multi-intent queries
                "resolved_query": str,     # After coreference resolution
            }
        """
        # Step 1: Resolve coreferences if history is provided
        resolved_query = query
        if conversation_history:
            resolved_query = self._resolve_coreferences(query, conversation_history, schema_context)

        # Step 2: Classify with CoT
        prompt = self._build_cot_intent_prompt(resolved_query, schema_context)

        raw = _call_groq_with_retry(
            self.client,
            self.model,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a senior database engineer. You MUST reason step-by-step "
                        "before classifying intent. Output ONLY valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
            max_tokens=900,
        )

        if not raw:
            return self._fallback_intent(query)

        result = _extract_json(raw)
        if not result:
            logger.warning(f"[NLPProcessor] Could not parse JSON from: {raw[:200]}")
            return self._fallback_intent(query)

        # Validate intent
        intent = result.get("intent", INTENT_UNKNOWN)
        if intent not in VALID_INTENTS:
            intent = INTENT_UNKNOWN

        confidence = float(result.get("confidence", 0.0))
        entities = result.get("entities", {})
        reasoning = result.get("reasoning", "")
        sub_tasks = result.get("sub_tasks", [])

        logger.info(
            f"[NLPProcessor] Intent={intent} confidence={confidence:.2f} "
            f"sub_tasks={len(sub_tasks)}"
        )

        return {
            "intent": intent,
            "confidence": confidence,
            "entities": entities,
            "reasoning": reasoning,
            "sub_tasks": sub_tasks,
            "resolved_query": resolved_query,
        }

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------

    def extract_entities(
        self,
        query: str,
        intent: str,
        schema_context: str = "",
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Extract structured entities with schema-grounded resolution.
        Infers implicit join conditions from FK relationships described
        in schema_context.
        """
        prompt = self._build_entity_extraction_prompt(
            query, intent, schema_context, conversation_history
        )

        raw = _call_groq_with_retry(
            self.client,
            self.model,
            [
                {
                    "role": "system",
                    "content": (
                        "You are an expert at extracting structured database query information. "
                        "Only reference tables and columns that exist in the provided schema. "
                        "Output ONLY valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
            max_tokens=700,
        )

        if not raw:
            return {}

        result = _extract_json(raw)
        return result or {}

    # ------------------------------------------------------------------
    # Coreference resolution
    # ------------------------------------------------------------------

    def _resolve_coreferences(
        self,
        query: str,
        history: List[Dict[str, str]],
        schema_context: str,
    ) -> str:
        """
        Resolve pronouns and implicit references in the query using
        recent conversation history.

        E.g. "show me their emails" → "show me the users' emails"
        """
        if not history:
            return query

        # Only use last 6 messages to keep context tight
        recent = history[-6:]
        history_text = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
            for m in recent
        )

        prompt = f"""Given this conversation history:
{history_text}

And this new query: "{query}"

If the new query contains pronouns (they, their, it, those, these, that, etc.) or 
implicit references to prior results, rewrite it as a fully self-contained query 
that explicitly names the tables and entities being referenced.

If the query is already self-contained, return it unchanged.

Return ONLY the rewritten query as a plain string (no JSON, no explanation)."""

        raw = _call_groq_with_retry(
            self.client,
            self.model,
            [
                {
                    "role": "system",
                    "content": "You resolve pronoun references in database queries. Return only the rewritten query.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=200,
        )

        if raw and len(raw) > 5:
            logger.debug(f"[NLPProcessor] Coreference: '{query}' → '{raw}'")
            return raw.strip().strip('"').strip("'")
        return query

    # ------------------------------------------------------------------
    # Safety check
    # ------------------------------------------------------------------

    def validate_query_safety(self, query: str) -> Dict[str, Any]:
        """Check if a natural language query contains dangerous intent."""
        dangerous_keywords = [
            "drop", "truncate", "alter table", "create table",
            "grant", "revoke", "exec", "execute", "shutdown",
        ]
        query_lower = query.lower()
        found = [kw for kw in dangerous_keywords if kw in query_lower]
        is_safe = len(found) == 0
        return {
            "is_safe": is_safe,
            "dangerous_keywords": found,
            "message": (
                "Query appears safe"
                if is_safe
                else f"Query contains dangerous operations: {', '.join(found)}"
            ),
        }

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_cot_intent_prompt(self, query: str, schema_context: str) -> str:
        return f"""Analyze this natural language database query using step-by-step reasoning.

Query: "{query}"

Database Schema:
{schema_context if schema_context else "No tables found (database is empty). DDL operations are possible."}

STEP 1 — Identify the operation type:
  What is the user trying to do? (read data, insert, update, delete, modify schema, or get schema info?)

STEP 2 — Identify entities:
  Which tables, columns, conditions, aggregations, and time ranges are mentioned or implied?
  IMPORTANT: Only reference tables and columns that exist in the schema above.

STEP 3 — Detect sub-tasks:
  Does this query contain multiple distinct operations? If so, list them in order.

STEP 4 — Assess confidence:
  How confident are you in the classification? (0.0 to 1.0)
  If < 0.6, set intent to UNKNOWN.

Return your analysis as JSON:
{{
    "reasoning": "Step-by-step reasoning here",
    "intent": "QUERY|INSERT|UPDATE|DELETE|DDL|SCHEMA_INFO|UNKNOWN",
    "confidence": 0.95,
    "entities": {{
        "tables": ["table1"],
        "columns": ["col1", "col2"],
        "conditions": ["condition description"],
        "aggregations": ["count", "sum"],
        "time_range": "last 7 days",
        "sort_order": "DESC by created_at",
        "limit": 10,
        "values": {{"col": "value"}}
    }},
    "sub_tasks": [
        {{"order": 1, "intent": "QUERY", "description": "fetch X"}},
        {{"order": 2, "intent": "UPDATE", "description": "update Y"}}
    ]
}}

Return ONLY the JSON object."""

    def _build_entity_extraction_prompt(
        self,
        query: str,
        intent: str,
        schema_context: str,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        history_section = ""
        if history:
            recent = history[-4:]
            history_section = "\nRecent conversation:\n" + "\n".join(
                f"  {m.get('role','user').upper()}: {m.get('content','')}"
                for m in recent
            )

        return f"""Extract detailed structured information from this database query.

Query: "{query}"
Intent: {intent}

Database Schema:
{schema_context if schema_context else "No schema available"}
{history_section}

Rules:
1. ONLY reference tables and columns that exist in the schema above
2. Infer implicit join conditions from foreign key relationships shown in the schema
3. If a column is ambiguous, qualify it with the table name (e.g., users.id)
4. For INSERT/UPDATE, extract the exact values to be written
5. For time-based filters, use the exact column name from the schema

Return as JSON:
{{
    "tables": ["table1", "table2"],
    "columns": ["table1.col1", "col2"],
    "conditions": ["users.is_active = true"],
    "joins": [{{"from": "orders.user_id", "to": "users.id"}}],
    "aggregations": ["COUNT(*)", "SUM(amount)"],
    "group_by": ["category"],
    "order_by": [{{"column": "created_at", "direction": "DESC"}}],
    "limit": 10,
    "offset": 0,
    "values": {{"name": "John", "age": 30}},
    "time_filter": {{"column": "created_at", "range": "last 7 days"}}
}}

Return ONLY the JSON object."""

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_intent(query: str) -> Dict[str, Any]:
        return {
            "intent": INTENT_UNKNOWN,
            "confidence": 0.0,
            "entities": {},
            "reasoning": "Failed to parse LLM response",
            "sub_tasks": [],
            "resolved_query": query,
        }
