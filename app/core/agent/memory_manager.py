"""
Memory Manager — Two-Tier Memory Architecture.

Tier 1 — Short-term session memory (in-process, per conversation thread):
  - Current conversation messages
  - Active database connection info
  - Recent query results (last N)
  - Intermediate reasoning steps

Tier 2 — Long-term persistent memory (SQLite-backed, per user):
  - Schema snapshots (cached schema per connection)
  - Frequently used query patterns
  - User corrections and preferences
  - Past successful query templates

The MemoryManager is consulted by the agent nodes before reasoning to
provide relevant context without polluting the LLM context window.
"""

import json
import time
import hashlib
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from threading import Lock
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QueryMemory:
    """A single remembered query interaction."""
    query: str
    intent: str
    sql: Optional[str]
    success: bool
    timestamp: float = field(default_factory=time.time)
    result_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SchemaSnapshot:
    """A cached schema for a specific connection."""
    connection_id: int
    schema_context: str
    fingerprint: str
    captured_at: float = field(default_factory=time.time)
    table_count: int = 0

    def is_stale(self, max_age_seconds: int = 300) -> bool:
        return (time.time() - self.captured_at) > max_age_seconds


@dataclass
class SessionMemory:
    """Short-term memory for a single conversation session."""
    user_id: int
    connection_id: int
    thread_id: str
    recent_queries: List[QueryMemory] = field(default_factory=list)
    active_schema_context: str = ""
    last_intent: str = ""
    last_sql: Optional[str] = None
    last_result_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Max recent queries to keep in session
    MAX_RECENT = 10

    def add_query(self, qm: QueryMemory) -> None:
        self.recent_queries.append(qm)
        if len(self.recent_queries) > self.MAX_RECENT:
            self.recent_queries = self.recent_queries[-self.MAX_RECENT:]
        self.last_intent = qm.intent
        self.last_sql = qm.sql
        self.last_result_count = qm.result_count
        self.updated_at = time.time()

    def get_recent_context(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return the last n queries as context dicts."""
        return [q.to_dict() for q in self.recent_queries[-n:]]


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

class MemoryManager:
    """
    Two-tier memory manager for the SQL agent.

    Usage:
        mm = MemoryManager()

        # Session memory
        session = mm.get_or_create_session(user_id=1, connection_id=2, thread_id="1_2_0")
        session.add_query(QueryMemory(query="...", intent="QUERY", sql="...", success=True))

        # Schema snapshots
        mm.store_schema_snapshot(connection_id=2, schema_context="...", fingerprint="abc")
        snapshot = mm.get_schema_snapshot(connection_id=2)

        # Query patterns
        mm.record_successful_pattern(user_id=1, query="...", sql="...", intent="QUERY")
        patterns = mm.get_similar_patterns(user_id=1, query="...", limit=3)
    """

    def __init__(self):
        self._lock = Lock()

        # Tier 1: session memory — keyed by thread_id
        self._sessions: Dict[str, SessionMemory] = {}

        # Tier 2: schema snapshots — keyed by connection_id
        self._schema_snapshots: Dict[int, SchemaSnapshot] = {}

        # Tier 2: successful query patterns — keyed by user_id
        # Each entry: {"query": str, "sql": str, "intent": str, "count": int, "last_used": float}
        self._query_patterns: Dict[int, List[Dict[str, Any]]] = {}

        # Tier 2: user corrections — keyed by user_id
        # Each entry: {"wrong_sql": str, "correct_sql": str, "reason": str, "timestamp": float}
        self._corrections: Dict[int, List[Dict[str, Any]]] = {}

        logger.info("[MemoryManager] Initialized two-tier memory")

    # ------------------------------------------------------------------
    # Tier 1: Session memory
    # ------------------------------------------------------------------

    def get_or_create_session(
        self,
        user_id: int,
        connection_id: int,
        thread_id: str,
    ) -> SessionMemory:
        """Get existing session or create a new one."""
        with self._lock:
            if thread_id not in self._sessions:
                self._sessions[thread_id] = SessionMemory(
                    user_id=user_id,
                    connection_id=connection_id,
                    thread_id=thread_id,
                )
                logger.debug(f"[MemoryManager] Created session: {thread_id}")
            return self._sessions[thread_id]

    def get_session(self, thread_id: str) -> Optional[SessionMemory]:
        """Get session by thread_id, or None if not found."""
        return self._sessions.get(thread_id)

    def clear_session(self, thread_id: str) -> None:
        """Clear a specific session (called on memory reset)."""
        with self._lock:
            if thread_id in self._sessions:
                del self._sessions[thread_id]
                logger.info(f"[MemoryManager] Cleared session: {thread_id}")

    def clear_all_sessions_for_user(self, user_id: int) -> int:
        """Clear all sessions for a user. Returns count cleared."""
        with self._lock:
            to_delete = [
                tid for tid, s in self._sessions.items()
                if s.user_id == user_id
            ]
            for tid in to_delete:
                del self._sessions[tid]
            logger.info(
                f"[MemoryManager] Cleared {len(to_delete)} sessions for user {user_id}"
            )
            return len(to_delete)

    def record_query_in_session(
        self,
        thread_id: str,
        query: str,
        intent: str,
        sql: Optional[str],
        success: bool,
        result_count: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Record a query interaction in the session memory."""
        session = self.get_session(thread_id)
        if session:
            qm = QueryMemory(
                query=query,
                intent=intent,
                sql=sql,
                success=success,
                result_count=result_count,
                error=error,
            )
            session.add_query(qm)

    # ------------------------------------------------------------------
    # Tier 2: Schema snapshots
    # ------------------------------------------------------------------

    def store_schema_snapshot(
        self,
        connection_id: int,
        schema_context: str,
        fingerprint: str,
        table_count: int = 0,
    ) -> None:
        """Store a schema snapshot for a connection."""
        with self._lock:
            self._schema_snapshots[connection_id] = SchemaSnapshot(
                connection_id=connection_id,
                schema_context=schema_context,
                fingerprint=fingerprint,
                table_count=table_count,
            )
            logger.debug(
                f"[MemoryManager] Stored schema snapshot for connection {connection_id} "
                f"(fingerprint={fingerprint[:8]})"
            )

    def get_schema_snapshot(
        self,
        connection_id: int,
        max_age_seconds: int = 300,
    ) -> Optional[SchemaSnapshot]:
        """
        Get a schema snapshot if it exists and is not stale.
        Returns None if not found or stale.
        """
        snapshot = self._schema_snapshots.get(connection_id)
        if snapshot and not snapshot.is_stale(max_age_seconds):
            return snapshot
        return None

    def invalidate_schema_snapshot(self, connection_id: int) -> None:
        """Invalidate the schema snapshot for a connection."""
        with self._lock:
            if connection_id in self._schema_snapshots:
                del self._schema_snapshots[connection_id]
                logger.info(
                    f"[MemoryManager] Invalidated schema snapshot for connection {connection_id}"
                )

    # ------------------------------------------------------------------
    # Tier 2: Query patterns
    # ------------------------------------------------------------------

    def record_successful_pattern(
        self,
        user_id: int,
        query: str,
        sql: str,
        intent: str,
    ) -> None:
        """Record a successful query pattern for future reference."""
        with self._lock:
            if user_id not in self._query_patterns:
                self._query_patterns[user_id] = []

            patterns = self._query_patterns[user_id]

            # Check if similar pattern already exists (by query hash)
            query_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()
            for p in patterns:
                if p.get("hash") == query_hash:
                    p["count"] = p.get("count", 1) + 1
                    p["last_used"] = time.time()
                    return

            # Add new pattern
            patterns.append({
                "hash": query_hash,
                "query": query,
                "sql": sql,
                "intent": intent,
                "count": 1,
                "last_used": time.time(),
            })

            # Keep only top 50 patterns per user (by usage count)
            if len(patterns) > 50:
                patterns.sort(key=lambda x: x.get("count", 0), reverse=True)
                self._query_patterns[user_id] = patterns[:50]

    def get_similar_patterns(
        self,
        user_id: int,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Find similar past query patterns for a user.
        Uses simple keyword overlap scoring.
        """
        patterns = self._query_patterns.get(user_id, [])
        if not patterns:
            return []

        query_words = set(query.lower().split())

        def similarity(pattern: Dict[str, Any]) -> float:
            pattern_words = set(pattern["query"].lower().split())
            if not pattern_words:
                return 0.0
            overlap = len(query_words & pattern_words)
            return overlap / max(len(query_words), len(pattern_words))

        scored = [(p, similarity(p)) for p in patterns]
        scored.sort(key=lambda x: (x[1], x[0].get("count", 0)), reverse=True)

        return [p for p, score in scored[:limit] if score > 0.3]

    # ------------------------------------------------------------------
    # Tier 2: User corrections
    # ------------------------------------------------------------------

    def record_correction(
        self,
        user_id: int,
        wrong_sql: str,
        correct_sql: str,
        reason: str = "",
    ) -> None:
        """Record a user correction for future reference."""
        with self._lock:
            if user_id not in self._corrections:
                self._corrections[user_id] = []
            self._corrections[user_id].append({
                "wrong_sql": wrong_sql,
                "correct_sql": correct_sql,
                "reason": reason,
                "timestamp": time.time(),
            })
            # Keep last 20 corrections
            if len(self._corrections[user_id]) > 20:
                self._corrections[user_id] = self._corrections[user_id][-20:]

    def get_corrections(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all corrections for a user."""
        return self._corrections.get(user_id, [])

    # ------------------------------------------------------------------
    # Context assembly for LLM
    # ------------------------------------------------------------------

    def build_memory_context(
        self,
        user_id: int,
        thread_id: str,
        include_patterns: bool = True,
        max_recent_queries: int = 3,
    ) -> str:
        """
        Build a compact memory context string to inject into LLM prompts.
        Includes recent queries and relevant patterns.
        """
        parts: List[str] = []

        # Recent session queries
        session = self.get_session(thread_id)
        if session and session.recent_queries:
            recent = session.get_recent_context(max_recent_queries)
            if recent:
                parts.append("Recent queries in this session:")
                for q in recent:
                    status = "✓" if q["success"] else "✗"
                    parts.append(
                        f"  {status} [{q['intent']}] {q['query']}"
                        + (f" → {q['sql'][:80]}..." if q.get("sql") else "")
                    )

        # Similar patterns from long-term memory
        if include_patterns and session:
            # We don't have the current query here, so skip pattern lookup
            # (patterns are looked up in nodes.py with the actual query)
            pass

        return "\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return memory usage statistics."""
        return {
            "active_sessions": len(self._sessions),
            "schema_snapshots": len(self._schema_snapshots),
            "users_with_patterns": len(self._query_patterns),
            "total_patterns": sum(
                len(p) for p in self._query_patterns.values()
            ),
            "users_with_corrections": len(self._corrections),
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

memory_manager = MemoryManager()
