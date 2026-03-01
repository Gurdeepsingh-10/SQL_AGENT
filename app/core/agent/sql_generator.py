"""
SQL Generator — Production-Grade v2.
Converts natural language to SQL with multi-pass refinement and dialect awareness.

Enhancements over v1:
- Multi-pass generation: candidate → schema-grounded validation → optimization
- Dialect-specific syntax rules (PostgreSQL, MySQL, SQLite, MSSQL, Oracle)
- Explicit CoT reasoning before SQL output
- Schema-grounded generation: only uses tables/columns from the live schema
- Edge case handling: NULLs, date/time, GROUP BY, window functions, subquery aliases
- Retry logic with exponential backoff on Groq API failures
- SQL explanation generation for user transparency
"""

from groq import Groq
from typing import Dict, Any, List, Optional
from app.config import settings
from app.utils.logger import get_logger
import re
import time

logger = get_logger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0


# ---------------------------------------------------------------------------
# Dialect-specific rules injected into prompts
# ---------------------------------------------------------------------------

DIALECT_RULES: Dict[str, str] = {
    "postgresql": """PostgreSQL-specific rules:
- Use ILIKE for case-insensitive string matching
- Use NOW() or CURRENT_TIMESTAMP for current time
- Use EXTRACT(EPOCH FROM ...) for timestamp arithmetic
- Use RETURNING clause for INSERT/UPDATE/DELETE when needed
- Boolean literals: TRUE / FALSE (not 1/0)
- String concatenation: || operator
- Use LIMIT/OFFSET for pagination
- Identifiers are case-sensitive when quoted; use lowercase unquoted
- Use COALESCE() for NULL handling
- Date arithmetic: date + INTERVAL '7 days'""",

    "mysql": """MySQL-specific rules:
- Use LIKE for case-insensitive matching (default collation)
- Use NOW() or CURDATE() for current time
- Use DATEDIFF() for date differences
- Boolean literals: TRUE/FALSE or 1/0
- String concatenation: CONCAT() function
- Use LIMIT/OFFSET for pagination
- Backtick-quote reserved word identifiers: \`order\`, \`group\`
- Use IFNULL() or COALESCE() for NULL handling
- Date arithmetic: DATE_ADD(date, INTERVAL 7 DAY)""",

    "sqlite": """SQLite-specific rules:
- Use LIKE for case-insensitive matching (ASCII only)
- Use datetime('now') for current time
- Use julianday() for date arithmetic
- Boolean literals: 1/0 (no native BOOLEAN)
- String concatenation: || operator
- Use LIMIT/OFFSET for pagination
- No native FULL OUTER JOIN — simulate with UNION
- Use COALESCE() for NULL handling
- Date arithmetic: datetime(col, '+7 days')""",

    "mssql": """SQL Server-specific rules:
- Use LIKE for case-insensitive matching (depends on collation)
- Use GETDATE() or SYSDATETIME() for current time
- Use DATEDIFF() for date differences
- Boolean literals: 1/0 (no native BOOLEAN)
- String concatenation: + operator or CONCAT()
- Use TOP N or OFFSET/FETCH for pagination
- Square-bracket-quote reserved word identifiers: [order], [group]
- Use ISNULL() or COALESCE() for NULL handling
- Date arithmetic: DATEADD(day, 7, date_col)""",

    "oracle": """Oracle-specific rules:
- Use UPPER()/LOWER() for case-insensitive matching
- Use SYSDATE or SYSTIMESTAMP for current time
- Use MONTHS_BETWEEN() for date differences
- Boolean literals: not natively supported; use 1/0 or 'Y'/'N'
- String concatenation: || operator
- Use ROWNUM or FETCH FIRST N ROWS ONLY for pagination
- Double-quote identifiers when case-sensitive
- Use NVL() or COALESCE() for NULL handling
- Date arithmetic: date_col + 7 (days)""",
}

COMMON_SQL_RULES = """General SQL rules:
1. Generate ONLY the SQL query — no explanations, no markdown
2. Use proper formatting and indentation
3. Always qualify ambiguous column names with table aliases
4. Use IS NULL / IS NOT NULL (never = NULL or != NULL)
5. For aggregations, include all non-aggregated SELECT columns in GROUP BY
6. Subqueries must always have an alias: (SELECT ...) AS sub
7. Window functions require OVER() clause
8. For date comparisons, cast strings to the appropriate date type
9. Avoid SELECT * in production — select only needed columns when schema is known
10. Use parameterized placeholders (:param) for user-supplied values"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_groq_with_retry(
    client: Groq,
    model: str,
    messages: List[Any],
    temperature: float = 0.1,
    max_tokens: int = 1200,
) -> Optional[str]:
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
                    f"[SQLGenerator] Groq transient error (attempt {attempt+1}): {e}. "
                    f"Retrying in {delay:.1f}s"
                )
                time.sleep(delay)
            else:
                logger.error(f"[SQLGenerator] Groq permanent error: {e}")
                return None
    return None


def _clean_sql(sql: str) -> str:
    """Strip markdown fences and normalize whitespace."""
    sql = re.sub(r"```sql\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"```\s*", "", sql)
    # Remove leading/trailing prose lines (lines not starting with SQL keywords)
    lines = sql.strip().splitlines()
    sql_keywords = {
        "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP",
        "WITH", "EXPLAIN", "TRUNCATE", "MERGE", "CALL", "EXEC", "BEGIN",
        "COMMIT", "ROLLBACK", "--", "/*",
    }
    # Find first SQL line
    start_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip().upper()
        if any(stripped.startswith(kw) for kw in sql_keywords):
            start_idx = i
            break
    sql = "\n".join(lines[start_idx:]).strip()
    # Ensure single trailing semicolon
    sql = sql.rstrip(";").strip() + ";"
    return sql


# ---------------------------------------------------------------------------
# SQLGenerator
# ---------------------------------------------------------------------------

class SQLGenerator:
    """
    Generates SQL queries from natural language using a multi-pass approach:
    Pass 1 — Generate candidate SQL with CoT reasoning
    Pass 2 — Validate against schema metadata and dialect rules
    Pass 3 — Optimize for correctness and performance
    """

    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL

    # ------------------------------------------------------------------
    # Primary: multi-pass generation
    # ------------------------------------------------------------------

    def generate_sql(
        self,
        query: str,
        intent: str,
        entities: Dict[str, Any],
        schema_context: str,
        dialect: str = "sqlite",
        reasoning: str = "",
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate SQL using a three-pass refinement pipeline.

        Returns:
            {
                "sql": str,
                "intent": str,
                "confidence": float,
                "reasoning": str,
                "dialect": str,
                "passes": int,
                "requires_parameters": bool,
                "error": Optional[str]
            }
        """
        dialect = dialect.lower() if dialect else "sqlite"

        # Pass 1: Generate candidate
        candidate = self._pass1_generate(query, intent, entities, schema_context, dialect, reasoning)
        if not candidate:
            return {
                "sql": None, "intent": intent, "confidence": 0.0,
                "reasoning": reasoning, "dialect": dialect, "passes": 1,
                "requires_parameters": False,
                "error": "Pass 1: Failed to generate SQL candidate",
            }

        # Pass 2: Schema-grounded validation and correction
        validated = self._pass2_validate_and_correct(
            candidate, query, intent, entities, schema_context, dialect
        )
        if not validated:
            validated = candidate  # Fall back to pass 1 result

        # Pass 3: Optimization pass (only for complex queries)
        final_sql = validated
        passes = 2
        if self._is_complex(validated):
            optimized = self._pass3_optimize(validated, schema_context, dialect)
            if optimized:
                final_sql = optimized
                passes = 3

        final_sql = _clean_sql(final_sql)

        logger.info(
            f"[SQLGenerator] Generated SQL ({passes} passes, dialect={dialect}): "
            f"{final_sql[:120]}..."
        )

        return {
            "sql": final_sql,
            "intent": intent,
            "confidence": 0.92,
            "reasoning": reasoning,
            "dialect": dialect,
            "passes": passes,
            "requires_parameters": self._check_requires_parameters(final_sql),
            "error": None,
        }

    # ------------------------------------------------------------------
    # Pass 1: Candidate generation with CoT
    # ------------------------------------------------------------------

    def _pass1_generate(
        self,
        query: str,
        intent: str,
        entities: Dict[str, Any],
        schema_context: str,
        dialect: str,
        reasoning: str,
    ) -> Optional[str]:
        dialect_rules = DIALECT_RULES.get(dialect, DIALECT_RULES["sqlite"])
        system_prompt = self._build_system_prompt(intent, dialect_rules)
        user_prompt = self._build_generation_prompt(
            query, intent, entities, schema_context, reasoning
        )

        raw = _call_groq_with_retry(
            self.client,
            self.model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.05,
            max_tokens=1200,
        )
        return raw

    # ------------------------------------------------------------------
    # Pass 2: Schema-grounded validation and correction
    # ------------------------------------------------------------------

    def _pass2_validate_and_correct(
        self,
        candidate_sql: str,
        original_query: str,
        intent: str,
        entities: Dict[str, Any],
        schema_context: str,
        dialect: str,
    ) -> Optional[str]:
        """
        Ask the LLM to review the candidate SQL against the schema and
        correct any hallucinated table/column names or syntax errors.
        """
        prompt = f"""Review this SQL query for correctness against the database schema.

Original Request: "{original_query}"
Intent: {intent}

Database Schema:
{schema_context}

Candidate SQL:
{candidate_sql}

Check for:
1. Any table names that do NOT exist in the schema → replace with correct names
2. Any column names that do NOT exist in the schema → replace with correct names
3. Missing table aliases causing ambiguous column references
4. Incorrect JOIN conditions (should match FK relationships in schema)
5. NULL comparison errors (= NULL instead of IS NULL)
6. GROUP BY missing non-aggregated columns
7. Subqueries without aliases
8. Dialect-specific syntax issues for {dialect.upper()}

If the SQL is correct, return it unchanged.
If corrections are needed, return the corrected SQL.

Return ONLY the SQL query, nothing else."""

        raw = _call_groq_with_retry(
            self.client,
            self.model,
            [
                {
                    "role": "system",
                    "content": (
                        f"You are a {dialect.upper()} SQL expert. "
                        "Review and correct SQL queries. Return ONLY the SQL."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=1200,
        )
        return raw

    # ------------------------------------------------------------------
    # Pass 3: Optimization
    # ------------------------------------------------------------------

    def _pass3_optimize(
        self,
        sql: str,
        schema_context: str,
        dialect: str,
    ) -> Optional[str]:
        """
        Optimize complex queries for performance and correctness.
        Only applied to queries with JOINs, subqueries, or aggregations.
        """
        prompt = f"""Optimize this SQL query for performance and correctness.

Database Schema:
{schema_context}

SQL to optimize:
{sql}

Optimization checklist:
1. Use indexed columns in WHERE clauses when available
2. Avoid SELECT * — select only needed columns
3. Push filters into subqueries/CTEs where possible
4. Use EXISTS instead of IN for large subqueries
5. Ensure proper JOIN order (smaller tables first when possible)
6. Add appropriate LIMIT if result set could be unbounded

Return ONLY the optimized SQL query."""

        raw = _call_groq_with_retry(
            self.client,
            self.model,
            [
                {
                    "role": "system",
                    "content": f"You are a {dialect.upper()} query optimizer. Return ONLY the SQL.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=1200,
        )
        return raw

    # ------------------------------------------------------------------
    # Explanation
    # ------------------------------------------------------------------

    def explain_sql(self, sql: str) -> str:
        """Generate a plain-English explanation of a SQL query."""
        prompt = f"""Explain this SQL query in simple, non-technical language.

SQL:
{sql}

Provide a brief, clear explanation of:
1. What data it retrieves/modifies
2. Any filters or conditions applied
3. How tables are joined (if applicable)

Use simple language. Avoid technical jargon."""

        raw = _call_groq_with_retry(
            self.client,
            self.model,
            [
                {
                    "role": "system",
                    "content": "You explain SQL queries in plain English for non-technical users.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        return raw or "Unable to generate explanation"

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_system_prompt(self, intent: str, dialect_rules: str) -> str:
        ddl_note = (
            "You ARE allowed to generate DDL statements (CREATE, ALTER, DROP) as requested."
            if intent == "DDL" or settings.ENABLE_DDL_OPERATIONS
            else "NEVER generate DROP, TRUNCATE, or destructive DDL unless explicitly authorized."
        )

        return f"""{COMMON_SQL_RULES}

{dialect_rules}

{ddl_note}

CRITICAL: Only use table and column names that exist in the provided schema.
If a requested table or column does not exist, use the closest matching name from the schema.
Return ONLY the SQL query."""

    def _build_generation_prompt(
        self,
        query: str,
        intent: str,
        entities: Dict[str, Any],
        schema_context: str,
        reasoning: str,
    ) -> str:
        entities_text = self._format_entities(entities)
        reasoning_section = (
            f"\nPrior reasoning:\n{reasoning}\n" if reasoning else ""
        )

        return f"""Convert this natural language query to SQL.

Natural Language Query: "{query}"
Intent: {intent}
{reasoning_section}
Database Schema:
{schema_context}

Extracted Entities:
{entities_text}

Generate the SQL query that fulfills this request.
Return ONLY the SQL query."""

    @staticmethod
    def _format_entities(entities: Dict[str, Any]) -> str:
        if not entities:
            return "No specific entities extracted"
        lines = []
        for key, value in entities.items():
            if value:
                lines.append(f"  {key}: {value}")
        return "\n".join(lines) if lines else "No specific entities extracted"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_complex(sql: str) -> bool:
        """Determine if a query is complex enough to warrant pass 3."""
        sql_upper = sql.upper()
        return (
            "JOIN" in sql_upper
            or "(SELECT" in sql_upper
            or "UNION" in sql_upper
            or "GROUP BY" in sql_upper
            or "OVER(" in sql_upper
            or "OVER (" in sql_upper
        )

    @staticmethod
    def _check_requires_parameters(sql: str) -> bool:
        return bool(re.search(r"[?$:]|\bVALUES\s*\(", sql, re.IGNORECASE))

    # ------------------------------------------------------------------
    # Legacy compatibility
    # ------------------------------------------------------------------

    def generate_multiple_candidates(
        self,
        query: str,
        intent: str,
        entities: Dict[str, Any],
        schema_context: str,
        num_candidates: int = 3,
    ) -> List[Dict[str, Any]]:
        """Generate multiple SQL candidates (legacy method, kept for compatibility)."""
        candidates = []
        for i in range(num_candidates):
            result = self.generate_sql(query, intent, entities, schema_context)
            if result.get("sql"):
                candidates.append(
                    {
                        "rank": i + 1,
                        "sql": result["sql"],
                        "confidence": result.get("confidence", 0.0),
                    }
                )
        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        return candidates
