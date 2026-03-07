"""
Dashboard API — Production Grade.
Provides real DB telemetry and real agent analytics from stored query history.
LangSmith integration for token tracking (reads live runs when API key is set).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import Dict, Any, List
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import time

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.models.user_connection import UserConnection
from app.models.query_history import QueryHistory
from app.core.connection_manager import connection_manager
from app.core.agent.nodes import _get_cached_inspector  # reuses per-engine TTL cache
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _get_langsmith_token_stats() -> Dict[str, Any]:
    """Pull real token usage stats from LangSmith SDK if configured."""
    tracing_enabled = settings.LANGSMITH_TRACING.lower() == "true"
    api_key = settings.LANGSMITH_API_KEY
    project = settings.LANGSMITH_PROJECT

    if not tracing_enabled or not api_key:
        return {"configured": False, "total_tokens": None, "total_cost_usd": None}

    try:
        from langsmith import Client
        client = Client(api_key=api_key)

        # Grab last 100 root runs from this project
        runs = list(client.list_runs(
            project_name=project,
            execution_order=1,  # root runs only
            limit=100,
            error=False,
        ))

        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for run in runs:
            usage = getattr(run, "total_tokens", None) or 0
            # Some SDK versions expose these differently
            if hasattr(run, "prompt_tokens"):
                total_prompt_tokens += run.prompt_tokens or 0
            if hasattr(run, "completion_tokens"):
                total_completion_tokens += run.completion_tokens or 0
            total_tokens += usage

        return {
            "configured": True,
            "total_tokens": total_tokens,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "run_count": len(runs),
        }
    except Exception as e:
        logger.warning(f"LangSmith SDK fetch failed: {e}")
        return {"configured": True, "total_tokens": None, "error": str(e)}


# ── DB Telemetry ──────────────────────────────────────────────────────────────

@router.get("/{connection_id}/db-telemetry")
async def get_db_telemetry(
    connection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Fetch live database telemetry — tables, rows, size, schema details, column stats."""

    connection = db.query(UserConnection).filter(
        UserConnection.id == connection_id,
        UserConnection.user_id == current_user.id,
        UserConnection.is_active == True
    ).first()

    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        decrypted_url = connection_manager.decrypt_connection_url(connection.connection_url)
        engine = connection_manager.get_engine(connection.id, decrypted_url)

        inspector = _get_cached_inspector(engine)
        full_schema = inspector.get_full_schema()

        total_tables = full_schema.get("total_tables", 0)
        tables_dict = full_schema.get("tables", {})

        total_rows = sum(t.get("row_count", 0) for t in tables_dict.values())
        total_columns = sum(len(t.get("columns", [])) for t in tables_dict.values())

        # DB Size (PostgreSQL)
        db_size_str = "N/A"
        if "postgresql" in decrypted_url:
            try:
                with engine.connect() as conn:
                    result = conn.execute(
                        text("SELECT pg_size_pretty(pg_database_size(current_database()))")
                    )
                    db_size_str = result.scalar()
            except Exception as e:
                logger.warning(f"Could not fetch DB size: {e}")

        # Per-table schema details (row count + column count + pk info)
        schema_details = {}
        column_counts = {}
        tables_no_pk = 0
        for name, info in tables_dict.items():
            cols = info.get("columns", [])
            col_count = len(cols)
            has_pk = any(c.get("primary_key") for c in cols)
            if not has_pk:
                tables_no_pk += 1
            schema_details[name] = {
                "row_count": info.get("row_count", 0),
                "col_count": col_count,
                "has_pk": has_pk,
            }
            column_counts[name] = col_count

        # Active pool connections via SQLAlchemy pool status
        pool = engine.pool
        try:
            pool_size = pool.size()  # configured pool_size
            checked_out = pool.checkedout()  # currently in use
        except Exception:
            pool_size = 0
            checked_out = 0

        # DB dialect + version
        try:
            with engine.connect() as conn:
                ver = conn.execute(text("SELECT version()")).scalar()
                dialect_version = str(ver)[:60] if ver else engine.dialect.name
        except Exception:
            dialect_version = engine.dialect.name

        return {
            "success": True,
            "metrics": {
                "total_tables": total_tables,
                "total_rows": total_rows,
                "total_columns": total_columns,
                "db_size": db_size_str,
                "status": "Healthy",
                # New metrics
                "tables_no_pk": tables_no_pk,
                "active_connections": checked_out,
                "pool_size": pool_size,
                "dialect_version": dialect_version,
            },
            "schema_details": schema_details,
            "column_counts": column_counts,
        }

    except Exception as e:
        logger.error(f"DB telemetry error: {e}")
        return {"success": False, "error": str(e)}


# ── Agent Telemetry ───────────────────────────────────────────────────────────

@router.get("/{connection_id}/agent-telemetry")
async def get_agent_telemetry(
    connection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Fetch comprehensive agent analytics — latency trend, intent pie, success/fail, LangSmith tokens."""

    connection = db.query(UserConnection).filter(
        UserConnection.id == connection_id,
        UserConnection.user_id == current_user.id
    ).first()

    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    # Fetch last 100 queries for this user
    recent_queries = (
        db.query(QueryHistory)
        .filter(QueryHistory.user_id == current_user.id)
        .order_by(QueryHistory.created_at.desc())
        .limit(100)
        .all()
    )

    total_queries = len(recent_queries)

    # Fetch LangSmith data up front — needed for cost metrics below
    langsmith_stats = _get_langsmith_token_stats()

    if total_queries == 0:
        return {
            "success": True,
            "metrics": {
                "avg_latency": "0.0s", "peak_latency": "0.0s",
                "total_queries": 0,
                "success_rate": "0%",
                "successful": 0, "failed": 0,
                "langsmith": langsmith_stats,
                "est_cost_usd": "$0.0000",
                "avg_tokens_per_query": 0,
            },
            "history": [],
            "intent_distribution": {},
            "latency_trend": [],
        }

    # ── Aggregates ────────────────────────────────────────────────────────────
    successful = sum(1 for q in recent_queries if q.success)
    failed = total_queries - successful
    success_rate = round((successful / total_queries) * 100)

    valid_latencies = [q.execution_time for q in recent_queries if q.execution_time is not None]
    avg_latency = sum(valid_latencies) / len(valid_latencies) if valid_latencies else 0.0
    peak_latency = max(valid_latencies) if valid_latencies else 0.0
    avg_tokens_per_query = round(langsmith_stats.get("total_tokens", 0) / total_queries, 1) if total_queries else 0

    # Estimated cost (Llama-3 70B on Groq: ~$0.0009 / 1k tokens)
    total_tokens = langsmith_stats.get("total_tokens") or 0
    est_cost_usd = round((total_tokens / 1000) * 0.0009, 4)

    # ── Intent Distribution ───────────────────────────────────────────────────
    intent_counts: Dict[str, int] = defaultdict(int)
    for q in recent_queries:
        intent_counts[q.intent or "UNKNOWN"] += 1

    # ── Latency Trend (last 15 queries, chronological) ────────────────────────
    chrono = list(reversed(recent_queries[:15]))
    latency_trend = [
        {
            "label": f"Q{i+1}",
            "latency": round(q.execution_time or 0, 2),
            "timestamp": q.created_at.isoformat(),
        }
        for i, q in enumerate(chrono)
    ]

    # ── Query History (detail rows) ───────────────────────────────────────────
    history_payload = [
        {
            "id": q.id,
            "timestamp": q.created_at.isoformat(),
            "prompt": q.natural_language_query,
            "intent": q.intent or "UNKNOWN",
            "latency": round(q.execution_time or 0, 2),
            "status": "Success" if q.success else "Failed",
        }
        for q in recent_queries[:15]
    ]

    # ── LangSmith token display ─────────────────────────────────────────
    if langsmith_stats.get("configured") and langsmith_stats.get("total_tokens") is not None:
        t = langsmith_stats["total_tokens"]
        token_display = f"{t:,} tokens"
    elif langsmith_stats.get("configured"):
        token_display = "⚠ LS Error"
    else:
        token_display = "Not Configured"

    return {
        "success": True,
        "metrics": {
            "avg_latency": f"{avg_latency:.2f}s",
            "peak_latency": f"{peak_latency:.2f}s",
            "total_queries": total_queries,
            "success_rate": f"{success_rate}%",
            "successful": successful,
            "failed": failed,
            "langsmith": langsmith_stats,
            "token_display": token_display,
            "est_cost_usd": f"${est_cost_usd:.4f}",
            "avg_tokens_per_query": avg_tokens_per_query,
        },
        "history": history_payload,
        "intent_distribution": dict(intent_counts),
        "latency_trend": latency_trend,
    }
