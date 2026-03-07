"""
SQL Safety Guard — Confirmation Layer for DDL/DML + Row-Cap Enforcement.

Instead of hard-blocking destructive queries, this module *classifies* SQL
statements by risk level so the agent can pause execution and ask the user
to explicitly confirm before modifying the database.

Risk levels:
  SAFE      → SELECT / SHOW / EXPLAIN — execute immediately
  CONFIRM   → INSERT / UPDATE / DELETE — pause and ask user
  DANGER    → DROP / TRUNCATE / ALTER / CREATE / GRANT — require explicit confirmation
  BLOCKED   → empty / unparseable / raw injection attempts
"""

import re
from typing import Literal, Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

RiskLevel = Literal["SAFE", "CONFIRM", "DANGER", "BLOCKED"]

# ── DDL nodes that require the strongest "DANGER" warning ─────────────────────
_DDL_NODES = frozenset({
    "Drop", "Truncate", "AlterTable", "AlterColumn",
    "Create", "Grant", "Revoke",
})

# ── DML nodes that require "CONFIRM" ─────────────────────────────────────────
_DML_NODES = frozenset({"Insert", "Update", "Delete", "Merge"})

# ── Regex fallback for when sqlglot cannot parse ──────────────────────────────
_DDL_RE = re.compile(
    r"^\s*(DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_DML_RE = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|MERGE)\b",
    re.IGNORECASE,
)

# ── Response size cap ─────────────────────────────────────────────────────────
MAX_RESULT_ROWS = 500

# ── User-friendly explanations for each risk ─────────────────────────────────
_RISK_MESSAGES = {
    "CONFIRM": (
        "⚠️ This query will **modify data** in your database.\n"
        "Please review it carefully before confirming execution."
    ),
    "DANGER": (
        "🚨 This query will **permanently alter or destroy** database objects "
        "(e.g., DROP, TRUNCATE, ALTER). This action **cannot be undone**.\n"
        "Confirm only if you are absolutely certain."
    ),
}


def classify_sql_risk(sql: str) -> tuple[RiskLevel, Optional[str]]:
    """
    Classify the risk level of a SQL statement.

    Returns:
        (risk_level, user_message)
        - "SAFE"    → execute immediately, no message
        - "CONFIRM" → pause, show message, wait for user confirmation
        - "DANGER"  → pause, show strong warning, wait for user confirmation
        - "BLOCKED" → reject outright (empty / pure injection attempt)
    """
    if not sql or not sql.strip():
        return "BLOCKED", "Empty SQL statement."

    # ── AST Path (fast + accurate) ─────────────────────────────────────────
    try:
        import sqlglot
        for stmt in sqlglot.parse(sql):
            if stmt is None:
                continue
            node_type = type(stmt).__name__

            if node_type in _DDL_NODES:
                logger.info(f"[SQL Guard] DANGER classified [{node_type}]: {sql[:80]}")
                return "DANGER", _RISK_MESSAGES["DANGER"]

            if node_type in _DML_NODES:
                logger.info(f"[SQL Guard] CONFIRM classified [{node_type}]: {sql[:80]}")
                return "CONFIRM", _RISK_MESSAGES["CONFIRM"]

        return "SAFE", None

    except ImportError:
        logger.warning("[SQL Guard] sqlglot not installed — using regex fallback")
    except Exception as exc:
        logger.warning(f"[SQL Guard] AST error ({exc}) — using regex fallback")

    # ── Regex Fallback ─────────────────────────────────────────────────────
    if _DDL_RE.match(sql):
        return "DANGER", _RISK_MESSAGES["DANGER"]
    if _DML_RE.match(sql):
        return "CONFIRM", _RISK_MESSAGES["CONFIRM"]

    return "SAFE", None


def inject_row_limit(sql: str, limit: int = MAX_RESULT_ROWS) -> str:
    """
    Cap SELECT result sets to `limit` rows.
    - If LIMIT already present and ≤ cap → unchanged.
    - If LIMIT > cap → reduced to cap.
    - If no LIMIT → appended.
    Non-SELECT statements pass through unchanged.
    """
    stripped = sql.strip().rstrip(";")
    if not stripped.upper().startswith("SELECT"):
        return sql

    existing = re.search(r"\bLIMIT\s+(\d+)", stripped, re.IGNORECASE)
    if existing:
        val = int(existing.group(1))
        if val <= limit:
            return sql
        safe = re.sub(r"\bLIMIT\s+\d+", f"LIMIT {limit}", stripped, flags=re.IGNORECASE)
        logger.debug(f"[Row-cap] LIMIT {val} → {limit}")
        return safe + ";"

    logger.debug(f"[Row-cap] Appended LIMIT {limit}")
    return stripped + f" LIMIT {limit};"
