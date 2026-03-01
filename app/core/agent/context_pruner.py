"""
Context Pruner — Intelligent Memory Management for LangGraph Agent.

Responsibilities:
1. Selective context pruning: removes stale/low-relevance messages while
   preserving schema context, user intent anchors, and recent results
2. Conversation summarization: compresses long histories into dense summaries
   before they exceed the LLM token limit
3. Token budget management: estimates token usage and triggers pruning
4. Schema context preservation: schema information is never pruned
5. Explicit clearance triggers: programmatic reset without losing schema knowledge

Token estimation uses a simple heuristic (4 chars ≈ 1 token) which is
conservative enough for most LLMs.
"""

from typing import List, Dict, Any, Optional, Tuple
from groq import Groq
from app.config import settings
from app.utils.logger import get_logger
import time
import re

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Approximate token budget for conversation history in the context window
# Llama 3 70B has 8192 token context; we reserve ~4000 for schema + query + response
_MAX_HISTORY_TOKENS = 3000
_CHARS_PER_TOKEN = 4  # Conservative estimate

# Message relevance scores (higher = more important to keep)
_RELEVANCE_SCHEMA = 10      # Schema information messages
_RELEVANCE_INTENT = 8       # Intent classification messages
_RELEVANCE_SQL = 7          # Generated SQL messages
_RELEVANCE_RESULT = 6       # Query result messages
_RELEVANCE_ERROR = 5        # Error messages (useful for re-reasoning)
_RELEVANCE_CLARIFY = 4      # Clarification messages
_RELEVANCE_GENERIC = 2      # Generic AI/human messages
_RELEVANCE_STALE = 1        # Old messages beyond recency window

# Number of most recent messages always preserved regardless of relevance
_ALWAYS_KEEP_RECENT = 4

# Summarization trigger: if history exceeds this many messages, summarize
_SUMMARIZE_THRESHOLD = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Estimate token count from character count."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _estimate_message_tokens(message: Any) -> int:
    """Estimate tokens for a LangChain message object."""
    content = ""
    if hasattr(message, "content"):
        content = str(message.content)
    elif isinstance(message, dict):
        content = str(message.get("content", ""))
    return _estimate_tokens(content) + 4  # +4 for role overhead


def _get_message_content(message: Any) -> str:
    """Extract content string from a message object or dict."""
    if hasattr(message, "content"):
        return str(message.content)
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(message)


def _get_message_type(message: Any) -> str:
    """Get message type/role."""
    if hasattr(message, "type"):
        return message.type
    if hasattr(message, "__class__"):
        return message.__class__.__name__.lower().replace("message", "")
    if isinstance(message, dict):
        return message.get("role", "unknown")
    return "unknown"


def _score_message_relevance(message: Any, index: int, total: int) -> int:
    """
    Score a message's relevance for pruning decisions.
    Higher score = more important to keep.
    """
    content = _get_message_content(message).lower()
    recency_position = total - index  # 1 = most recent

    # Always keep very recent messages
    if recency_position <= _ALWAYS_KEEP_RECENT:
        return 100

    # Schema information is always critical
    if any(kw in content for kw in ["table:", "column:", "database schema", "total tables"]):
        return _RELEVANCE_SCHEMA

    # SQL queries are important
    if any(kw in content for kw in ["select ", "insert ", "update ", "delete ", "create "]):
        return _RELEVANCE_SQL

    # Intent classification
    if any(kw in content for kw in ["intent:", "classified", "query intent", "schema_info"]):
        return _RELEVANCE_INTENT

    # Results
    if any(kw in content for kw in ["found ", "row(s)", "affected", "returned"]):
        return _RELEVANCE_RESULT

    # Errors
    if any(kw in content for kw in ["error", "failed", "invalid", "not found"]):
        return _RELEVANCE_ERROR

    # Clarification
    if any(kw in content for kw in ["clarif", "ambiguous", "which table", "could you"]):
        return _RELEVANCE_CLARIFY

    # Stale messages (older than recency window)
    if recency_position > 10:
        return _RELEVANCE_STALE

    return _RELEVANCE_GENERIC


# ---------------------------------------------------------------------------
# ContextPruner
# ---------------------------------------------------------------------------

class ContextPruner:
    """
    Manages conversation context to prevent token overflow and maintain
    relevant information for the agent's reasoning.
    """

    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL

    # ------------------------------------------------------------------
    # Primary: prune messages to fit token budget
    # ------------------------------------------------------------------

    def prune_messages(
        self,
        messages: List[Any],
        schema_context: str = "",
        max_tokens: int = _MAX_HISTORY_TOKENS,
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """
        Prune the message list to fit within the token budget.

        Strategy:
        1. Always keep the most recent _ALWAYS_KEEP_RECENT messages
        2. Score remaining messages by relevance
        3. Remove lowest-relevance messages until under budget
        4. Never remove schema-related messages

        Returns:
            (pruned_messages, stats_dict)
        """
        if not messages:
            return messages, {"pruned": 0, "kept": 0, "total_tokens": 0}

        total = len(messages)
        current_tokens = sum(_estimate_message_tokens(m) for m in messages)

        if current_tokens <= max_tokens:
            return messages, {
                "pruned": 0,
                "kept": total,
                "total_tokens": current_tokens,
            }

        logger.info(
            f"[ContextPruner] Pruning {total} messages "
            f"({current_tokens} tokens > {max_tokens} budget)"
        )

        # Score all messages
        scored: List[Tuple[int, int, Any]] = []  # (score, index, message)
        for i, msg in enumerate(messages):
            score = _score_message_relevance(msg, i, total)
            scored.append((score, i, msg))

        # Sort by score descending, then by recency (index descending)
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

        # Greedily keep messages until budget is exhausted
        kept_indices: set = set()
        running_tokens = 0

        for score, idx, msg in scored:
            msg_tokens = _estimate_message_tokens(msg)
            if running_tokens + msg_tokens <= max_tokens:
                kept_indices.add(idx)
                running_tokens += msg_tokens
            elif score >= _RELEVANCE_SCHEMA:
                # Always keep schema messages even if over budget
                kept_indices.add(idx)
                running_tokens += msg_tokens

        # Reconstruct in original order
        pruned_messages = [
            msg for i, msg in enumerate(messages) if i in kept_indices
        ]

        pruned_count = total - len(pruned_messages)
        logger.info(
            f"[ContextPruner] Pruned {pruned_count} messages, "
            f"kept {len(pruned_messages)} ({running_tokens} tokens)"
        )

        return pruned_messages, {
            "pruned": pruned_count,
            "kept": len(pruned_messages),
            "total_tokens": running_tokens,
        }

    # ------------------------------------------------------------------
    # Summarization
    # ------------------------------------------------------------------

    def should_summarize(self, messages: List[Any]) -> bool:
        """Check if the conversation history is long enough to warrant summarization."""
        return len(messages) >= _SUMMARIZE_THRESHOLD

    def summarize_history(
        self,
        messages: List[Any],
        schema_context: str = "",
        keep_recent: int = _ALWAYS_KEEP_RECENT,
    ) -> Tuple[List[Any], str]:
        """
        Summarize older conversation history into a compact summary message,
        keeping the most recent messages intact.

        Returns:
            (new_messages_list, summary_text)
            new_messages_list = [summary_message] + recent_messages
        """
        if len(messages) <= keep_recent:
            return messages, ""

        older = messages[:-keep_recent]
        recent = messages[-keep_recent:]

        # Build text for summarization
        history_text = "\n".join(
            f"{_get_message_type(m).upper()}: {_get_message_content(m)[:300]}"
            for m in older
        )

        summary = self._call_summarize(history_text, schema_context)

        if not summary:
            # Fallback: just drop older messages
            logger.warning("[ContextPruner] Summarization failed, dropping older messages")
            return recent, ""

        # Create a synthetic summary message
        from langchain_core.messages import AIMessage
        summary_msg = AIMessage(
            content=f"[CONVERSATION SUMMARY]\n{summary}"
        )

        new_messages = [summary_msg] + list(recent)

        logger.info(
            f"[ContextPruner] Summarized {len(older)} messages into 1 summary message"
        )

        return new_messages, summary

    def _call_summarize(self, history_text: str, schema_context: str) -> Optional[str]:
        """Call LLM to summarize conversation history."""
        prompt = f"""Summarize this database query conversation history concisely.
Focus on:
1. What the user was trying to accomplish
2. Which tables and columns were involved
3. What queries were executed and their results
4. Any errors or corrections made

Conversation:
{history_text[:3000]}

Return a dense 3-5 sentence summary that preserves all critical context."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[  # type: ignore[arg-type]
                    {
                        "role": "system",
                        "content": "You summarize database query conversations concisely.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=400,
            )
            content = response.choices[0].message.content
            return content.strip() if content else None
        except Exception as e:
            logger.error(f"[ContextPruner] Summarization error: {e}")
            return None

    # ------------------------------------------------------------------
    # Selective clearance
    # ------------------------------------------------------------------

    def clear_non_schema_messages(self, messages: List[Any]) -> List[Any]:
        """
        Remove all messages except schema-related ones.
        Used for soft reset: clears conversation without losing schema knowledge.
        """
        schema_messages = []
        for msg in messages:
            content = _get_message_content(msg).lower()
            if any(
                kw in content
                for kw in ["table:", "column:", "database schema", "total tables", "conversation summary"]
            ):
                schema_messages.append(msg)

        logger.info(
            f"[ContextPruner] Selective clear: kept {len(schema_messages)} "
            f"schema messages from {len(messages)} total"
        )
        return schema_messages

    # ------------------------------------------------------------------
    # Token budget check
    # ------------------------------------------------------------------

    def get_token_usage(self, messages: List[Any]) -> Dict[str, int]:
        """Return token usage statistics for the current message list."""
        total = sum(_estimate_message_tokens(m) for m in messages)
        return {
            "estimated_tokens": total,
            "budget": _MAX_HISTORY_TOKENS,
            "remaining": max(0, _MAX_HISTORY_TOKENS - total),
            "over_budget": max(0, total - _MAX_HISTORY_TOKENS),
            "message_count": len(messages),
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

context_pruner = ContextPruner()
