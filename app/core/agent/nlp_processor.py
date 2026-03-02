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
import hashlib
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
# Rule-based fast-path intent patterns (no LLM needed)
# ---------------------------------------------------------------------------

_FAST_INTENT_RULES = [
    # ── HIGHEST PRIORITY: DATA RETRIEVAL keywords ───────────────────────────
    # "show all entries", "get all records", "display rows/data/values", etc.
    # These are unambiguously data queries (QUERY), never schema queries.
    (re.compile(r'\b(entries|records|rows|data|values|content|items)\b', re.I), 'QUERY', 0.97),

    # ── 'show me the X table' → QUERY (show specific table content) ─────────
    # MUST be before SCHEMA_INFO rule. 'show me the teacher table' → QUERY.
    # Only triggers when a concrete table name (non-schema word) follows 'the'.
    (re.compile(
        r'^\s*(show|display|get)\s+(me\s+)?(the\s+)?(?!schema|all|list|columns|structure|database)\w+\s+table\b',
        re.I
    ), 'QUERY', 0.96),

    # ── SCHEMA_INFO — user wants table structure/list, not data ─────────────
    (re.compile(
        r'^\s*('
        r'show\s+(me\s+)?(the\s+)?(schema|tables|all\s+tables|columns|structure|database\s+schema)'
        r'|list\s+(all\s+)?tables'
        r'|what\s+(are\s+)?(the\s+)?tables'
        r'|which\s+tables'
        r'|what\s+tables'
        r'|describe\s+(the\s+)?(schema|database|tables)'
        r'|table\s+(list|structure|info|information)'
        r'|database\s+(schema|tables|structure)'
        r'|tell\s+me\s+(about\s+)?(the\s+)?(schema|tables)'
        r'|what\s+does\s+(the\s+)?database\s+(look\s+like|contain|have)'
        r'|how\s+many\s+tables'
        r')',
        re.I
    ), 'SCHEMA_INFO', 0.95),

    # ── DDL ─────────────────────────────────────────────────────────────────
    (re.compile(r'^\s*(create table|alter table|drop table|create index|create view|add column|rename|make table)\b', re.I), 'DDL', 0.92),

    # ── INSERT / POPULATE / ADD DATA ────────────────────────────────────────
    (re.compile(r'^\s*(insert|add|create\s+(a\s+)?record|new\s+entry|put|populate|fill|write|append)\b', re.I), 'INSERT', 0.95),

    # ── Standard QUERY ──────────────────────────────────────────────────────
    (re.compile(r'^\s*select\b', re.I), 'QUERY', 0.95),
    (re.compile(r'^\s*(count|how many|how much|total|sum|average|avg|min|max)\b', re.I), 'QUERY', 0.90),

    # ── DML mutations ───────────────────────────────────────────────────────
    (re.compile(r'^\s*(update|change|modify|set|edit)\b', re.I), 'UPDATE', 0.90),
    (re.compile(r'^\s*(delete|remove|drop record)\b', re.I), 'DELETE', 0.90),

    # ── Generic QUERY fallback — show/list/get/find/retrieve ────────────────
    # Note: 'show tables' is caught first by SCHEMA_INFO above.
    # This catches 'show me X', 'list all X', 'get X from Y', etc.
    (re.compile(r'^\s*(show|list|get|fetch|display|give me|tell me|find|retrieve|search|what is|what are)\b', re.I), 'QUERY', 0.88),
]

# Disqualify fast-path if query contains complex SQL indicators
_COMPLEX_INDICATORS = re.compile(
    r'\b(join|subquery|union|window|partition|having|cte|rank|dense_rank|lag|lead|rollup|cube|pivot|with\s+\w+\s+as)\b',
    re.I
)
# Disqualify if query has clear cross-turn pronoun references
_COREF_PRONOUNS = re.compile(
    r'\b(they|them|their|those|these|him|her|his|hers)\b',
    re.I
)

# ---------------------------------------------------------------------------
# In-memory response cache (intent classification)
# Key = MD5 hash(query_lower + schema_fingerprint)
# ---------------------------------------------------------------------------

_INTENT_CACHE: Dict[str, Dict[str, Any]] = {}
_INTENT_CACHE_MAX = 256  # evict oldest when full
_CACHE_HITS = 0
_CACHE_MISSES = 0


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

    v3 enhancements: rule-based fast-path, response caching, fast model by default.
    """

    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL
        self.fast_model = getattr(settings, 'GROQ_FAST_MODEL', 'llama-3.1-8b-instant')

    def _select_model(self, query: str) -> str:
        """Use the fast 8B model unless the query is clearly complex."""
        is_complex = bool(_COMPLEX_INDICATORS.search(query))
        return self.model if is_complex else self.fast_model

    # ------------------------------------------------------------------
    # Rule-based fast-path (zero LLM calls for obvious intents)
    # ------------------------------------------------------------------

    def _fast_intent(self, query: str, schema_context: str) -> Optional[Dict[str, Any]]:
        """
        Try to classify intent purely with regex rules.
        Returns None if the query is too complex for rule-based classification.
        """
        q = query.strip()
        # Don't fast-path if query has complex indicators or coreference pronouns
        if _COMPLEX_INDICATORS.search(q) or _COREF_PRONOUNS.search(q):
            return None
        # Don't fast-path if query is very long (likely complex)
        if len(q.split()) > 30:
            return None

        for pattern, intent, confidence in _FAST_INTENT_RULES:
            if pattern.search(q):
                logger.debug(f"[NLPProcessor] Fast-path intent={intent} for: {q[:60]}")
                return {
                    "intent": intent,
                    "confidence": confidence,
                    "entities": {},
                    "reasoning": f"Rule-based classification: {intent}",
                    "sub_tasks": [],
                    "resolved_query": query,
                }
        return None

    # ------------------------------------------------------------------
    # Response cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(query: str, schema_context: str) -> str:
        raw = f"{query.strip().lower()}|{schema_context[:500]}"
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    def _cache_get(key: str) -> Optional[Dict[str, Any]]:
        global _CACHE_HITS, _CACHE_MISSES
        if key in _INTENT_CACHE:
            _CACHE_HITS += 1
            return _INTENT_CACHE[key]
        _CACHE_MISSES += 1
        return None

    @staticmethod
    def _cache_set(key: str, value: Dict[str, Any]) -> None:
        global _INTENT_CACHE
        if len(_INTENT_CACHE) >= _INTENT_CACHE_MAX:
            # Evict oldest entry
            oldest = next(iter(_INTENT_CACHE))
            del _INTENT_CACHE[oldest]
        _INTENT_CACHE[key] = value

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
        Also extracts entities in the same call for efficiency.

        v3 optimizations:
        - Rule-based fast-path for obvious intents (zero LLM calls)
        - Response cache for repeated (query+schema) combinations
        - Fast 8B model by default, 70B only for complex queries
        - Coreference resolution only for clear pronoun references

        Returns:
            {
                "intent": str,
                "confidence": float,
                "entities": {...},
                "reasoning": str,
                "sub_tasks": [...],
                "resolved_query": str,
            }
        """
        # ── 1. Rule-based fast-path (no LLM call at all) ──────────────────
        # Always run fast-path first UNLESS the query has coreference pronouns
        # (it, them, their, those) which require history to resolve.
        # Previously this was skipped entirely with history, causing queries like
        # "show all entries in student" to be misrouted to SCHEMA_INFO by the LLM.
        if not self._needs_coreference(query):
            fast = self._fast_intent(query, schema_context)
            if fast is not None:
                return fast

        # ── 2. Coreference resolution (only for clear pronoun references) ──
        resolved_query = query
        # Only resolve if query has *clear* pronoun references AND history exists
        if conversation_history and self._needs_coreference(query):
            resolved_query = self._resolve_coreferences(query, conversation_history, schema_context) or query

        # ── 3. Response cache ─────────────────────────────────────────────
        cache_key = self._cache_key(resolved_query, schema_context)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug(f"[NLPProcessor] Cache hit for: {query[:60]}")
            return cached

        # ── 4. LLM call ───────────────────────────────────────────────────
        history_section = ""
        if conversation_history:
            recent = conversation_history[-4:]  # reduced from 6 to 4
            history_text = "\n".join(
                f"{m.get('role', 'user').upper()}: {m.get('content', '')[:200]}"
                for m in recent
            )
            history_section = f"\n\nRecent conversation:\n{history_text}"

        selected_model = self._select_model(query)

        prompt = f"""Classify this database query and extract entities.

Query: "{resolved_query}"
Database Schema:
{schema_context if schema_context else "No tables found. DDL operations are possible."}
{history_section}

Intent classification rules (CRITICAL — read carefully):
- SCHEMA_INFO: User wants to KNOW THE STRUCTURE of the database — tables list, column names, data types, relationships. Examples: "what tables exist", "describe the schema", "show me the columns of X"
- QUERY: User wants to READ DATA/ROWS from a table. Examples: "show all entries in X", "get all records from X", "list all rows", "show me the data in X", "select from X", "how many rows"
- INSERT: User wants to ADD new rows/records/data.
- UPDATE: User wants to CHANGE existing data.
- DELETE: User wants to REMOVE rows.
- DDL: User wants to CREATE, ALTER, or DROP a table/index.
- UNKNOWN: Cannot determine with confidence.

Key disambiguation:
- "show entries" or "show records" or "show data" or "show values" in a table → QUERY (they want rows, not schema)
- "show tables" or "show columns" or "show structure" → SCHEMA_INFO

Return ONLY this JSON:
{{
    "reasoning": "brief reasoning",
    "intent": "QUERY|INSERT|UPDATE|DELETE|DDL|SCHEMA_INFO|UNKNOWN",
    "confidence": 0.95,
    "entities": {{
        "tables": ["table1"],
        "columns": ["col1"],
        "conditions": ["condition"],
        "aggregations": [],
        "time_range": null,
        "sort_order": null,
        "limit": null,
        "values": {{}}
    }},
    "sub_tasks": []
}}"""

        raw = _call_groq_with_retry(
            self.client,
            selected_model,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a database engineer. Classify the query intent and extract entities. "
                        "Output ONLY valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
            max_tokens=600,  # reduced from 800
        )

        if not raw:
            return self._fallback_intent(query)

        result = _extract_json(raw)
        if not result:
            logger.warning(f"[NLPProcessor] Could not parse JSON from: {raw[:200]}")
            return self._fallback_intent(query)

        intent = result.get("intent", INTENT_UNKNOWN)
        if intent not in VALID_INTENTS:
            intent = INTENT_UNKNOWN

        confidence = float(result.get("confidence", 0.0))
        entities = result.get("entities", {})
        reasoning = result.get("reasoning", "")
        sub_tasks = result.get("sub_tasks", [])

        logger.info(
            f"[NLPProcessor] LLM intent={intent} confidence={confidence:.2f} "
            f"model={selected_model.split('-')[0]} sub_tasks={len(sub_tasks)}"
        )

        final_result = {
            "intent": intent,
            "confidence": confidence,
            "entities": entities,
            "reasoning": reasoning,
            "sub_tasks": sub_tasks,
            "resolved_query": resolved_query,
        }

        # Cache the result for future identical queries
        self._cache_set(cache_key, final_result)
        return final_result

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

    # Narrowed: only *clear* cross-turn pronoun references trigger resolution.
    # Words like "it", "that", "this", "where", "which" are too common in standalone
    # queries (e.g. "show all orders where status = 'shipped'") and cause false positives.
    PRONOUN_PATTERNS = re.compile(
        r'\b(they|them|their|those|these|him|her|his|hers)\b',
        re.I
    )

    def _needs_coreference(self, query: str) -> bool:
        """Quick check if query likely needs coreference resolution."""
        return bool(self.PRONOUN_PATTERNS.search(query))

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
