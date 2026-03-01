# Product Requirements Document (PRD)
## AI SQL Agent — Backend Platform

**Version:** 2.0.0  
**Date:** March 2026  
**Status:** Active Development — Production-Grade Upgrade  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals and Objectives](#3-goals-and-objectives)
4. [Target Users](#4-target-users)
5. [System Architecture Overview](#5-system-architecture-overview)
6. [Feature Specifications](#6-feature-specifications)
7. [Production-Grade Enhancements (v2)](#7-production-grade-enhancements-v2)
8. [API Reference Summary](#8-api-reference-summary)
9. [Data Models](#9-data-models)
10. [Security Requirements](#10-security-requirements)
11. [Configuration and Environment](#11-configuration-and-environment)
12. [Non-Functional Requirements](#12-non-functional-requirements)
13. [Known Limitations and Future Work](#13-known-limitations-and-future-work)

---

## 1. Executive Summary

**AI SQL Agent** is a full-stack backend platform that enables non-technical users to interact with relational databases using plain English. Users type natural language questions or commands (e.g., *"Show me all orders from last week"*), and the system automatically classifies intent, generates valid SQL, validates it for safety and schema correctness, executes it against the user's connected database, and returns structured results — all through a REST API backed by a retro-styled single-page web frontend.

**Version 2.0** introduces a production-grade upgrade that eliminates hallucinations, resolves agent stalling, implements robust memory management, and dramatically improves SQL generation accuracy across all supported database dialects.

The system is built on **FastAPI**, powered by **Groq's Llama 3 70B** LLM for NLP and SQL generation, orchestrated via a **LangGraph** stateful agent pipeline, and persists data in **SQLite** (with PostgreSQL support available).

---

## 2. Problem Statement

Relational databases are the backbone of most business data, yet querying them requires SQL knowledge that most business users lack. Existing BI tools are either too rigid (fixed dashboards) or too complex (require SQL expertise). There is a gap for a lightweight, conversational interface that:

- Accepts natural language questions about any connected database
- Generates and executes the correct SQL automatically
- **Does not hallucinate** table names, column names, or relationships
- **Does not stall** on ambiguous queries or tool failures
- Enforces safety guardrails to prevent destructive operations
- Supports multiple databases per user
- Provides a history of all interactions for auditability

---

## 3. Goals and Objectives

| Goal | Description |
|------|-------------|
| **Natural Language to SQL** | Convert any natural language database query into valid, executable SQL |
| **Zero Hallucination** | Every generated SQL is validated against the live schema before execution |
| **No Stalling** | Loop detection with configurable max iterations and graceful degradation |
| **Multi-Database Support** | Allow each user to connect and query multiple databases (SQLite, PostgreSQL, MySQL, MSSQL, Oracle) |
| **Security First** | Validate all generated SQL before execution; block injection, DDL, and destructive ops by default |
| **Conversation Memory** | Two-tier memory: short-term session + long-term persistent patterns |
| **Auditability** | Log every query, its generated SQL, intent, result count, and execution time |
| **Self-Contained UI** | Serve a retro-styled SPA frontend from the same FastAPI server |

---

## 4. Target Users

| User Type | Description |
|-----------|-------------|
| **Business Analysts** | Non-technical users who need to query databases without writing SQL |
| **Developers / DBAs** | Technical users who want a fast natural-language interface for exploration |
| **Product Teams** | Teams that need ad-hoc data access without involving engineering |
| **API Consumers** | External systems or scripts that integrate via the REST API |

---

## 5. System Architecture Overview

### 5.1 High-Level Architecture

```
User / Browser
    │
    ▼ HTTP REST
FastAPI Server
    ├── Auth Router (/auth)
    ├── Agent Router (/agent)  ──► LangGraph Pipeline
    ├── Connections Router (/connections)
    └── Database Router (/db)

LangGraph Pipeline
    ├── parse_intent node  ──► Groq LLM (CoT + coreference)
    ├── generate_sql node  ──► Groq LLM (multi-pass + dialect)
    ├── validate_sql node  ──► SchemaInspector (strict grounding)
    ├── execute_sql node   ──► Target Database (retry + classification)
    ├── get_schema_info node
    └── clarify_query node

Memory System
    ├── MemoryManager (two-tier)
    │   ├── Tier 1: SessionMemory (in-process, per thread)
    │   └── Tier 2: SchemaSnapshots + QueryPatterns + Corrections
    └── ContextPruner (selective pruning + summarization)

App Database (SQLite)
    ├── users
    ├── user_connections (encrypted URLs)
    └── query_history
```

### 5.2 LangGraph Agent Pipeline (v2)

```
START
  │
  ▼
parse_intent ──► [CoT reasoning, coreference resolution, multi-intent detection]
  │
  ├── SCHEMA_INFO ──► get_schema_info ──► END
  ├── UNKNOWN / low confidence ──► clarify_query ──► END
  └── QUERY/INSERT/UPDATE/DELETE/DDL
        │
        ▼
    generate_sql ──► [multi-pass: candidate → schema-validate → optimize]
        │
        ├── error ──► END
        └── SQL generated
              │
              ▼
          validate_sql ──► [strict schema check, injection, permissions]
              │
              ├── hard error (injection/permissions) ──► END
              ├── schema errors + attempts < MAX ──► generate_sql (re-reasoning loop)
              ├── schema errors + attempts >= MAX ──► END (graceful degradation)
              └── valid
                    │
                    ▼
                execute_sql ──► [retry with backoff, error classification]
                    │
                    └── END
```

**Loop Detection:** The `re_reasoning_attempts` counter in `AgentState` is incremented each time `validate_sql` triggers re-generation. When it reaches `MAX_RE_REASONING_ATTEMPTS` (default: 2), the graph routes to END with a clear error message instead of looping indefinitely.

### 5.3 Component Breakdown (v2)

| Component | File | Responsibility |
|-----------|------|----------------|
| `NLPProcessor` | `app/core/agent/nlp_processor.py` | CoT intent classification, coreference resolution, multi-intent decomposition |
| `SQLGenerator` | `app/core/agent/sql_generator.py` | 3-pass SQL generation: candidate → schema-validate → optimize; dialect-specific rules |
| `SQLValidator` | `app/core/agent/validator.py` | Strict schema cross-checking, injection detection, re-reasoning triggers |
| `SQLExecutor` | `app/core/agent/executor.py` | Retry with backoff, error classification (transient/schema/permission/permanent) |
| `SchemaInspector` | `app/core/agent/schema_inspector.py` | FK graph, fingerprint-based cache, `validate_references()`, `suggest_join_path()` |
| `MemoryManager` | `app/core/agent/memory_manager.py` | Two-tier memory: session + schema snapshots + query patterns + corrections |
| `ContextPruner` | `app/core/agent/context_pruner.py` | Selective pruning, summarization, token budget management |
| `ConnectionManager` | `app/core/connection_manager.py` | Multi-DB engine pool with Fernet encryption |
| `SessionManager` | `app/core/agent/graph.py` | Per-user, per-connection LangGraph thread management with memory integration |

---

## 6. Feature Specifications

### 6.1 Authentication

**Registration**
- Users register with `email`, `username`, and `password`
- Passwords are hashed using `bcrypt` via `passlib`
- Duplicate email or username returns HTTP 400

**Login**
- Accepts `email` + `password`
- Returns a signed **JWT** (HS256) with configurable expiry (default: 30 minutes)
- All protected endpoints require `Authorization: Bearer <token>`

**GitHub OAuth** *(Placeholder — not yet implemented)*
- Endpoints exist at `GET /auth/github/login` and `GET /auth/github/callback`

---

### 6.2 Database Connection Management

Users can register multiple external database connections. Each connection is:
- **Tested** before saving (live connection check)
- **Encrypted** at rest using Fernet symmetric encryption
- **Cached** as a SQLAlchemy engine pool for performance
- Marked as **active/inactive** and **default**

**Supported operations:**

| Operation | Endpoint | Description |
|-----------|----------|-------------|
| Test connection | `POST /connections/test` | Validate URL without saving |
| Add connection | `POST /connections/add` | Save new encrypted connection |
| List connections | `GET /connections/list` | List all user connections |
| Update connection | `PATCH /connections/{id}` | Rename, activate/deactivate, set default |
| Delete connection | `DELETE /connections/{id}` | Remove connection and close engine |

---

### 6.3 Natural Language Query Processing

The primary feature. Users submit a natural language query and optionally specify a `connection_id`. The system:

1. **Resolves the target database** — uses specified connection or falls back to the user's default
2. **Checks schema cache** — uses `MemoryManager` schema snapshot if fresh (< 5 min old)
3. **Gets or creates session memory** — `MemoryManager.get_or_create_session()`
4. **Invokes the LangGraph pipeline** — with all new state fields populated
5. **Records in memory** — session memory + long-term patterns on success
6. **Persists query history** — intent, SQL, success/failure, execution time, result count
7. **Returns structured response** — intent, generated SQL, results, execution time, message

**Intent Types:**

| Intent | SQL Operation | Example Query |
|--------|--------------|---------------|
| `QUERY` | SELECT | "Show me all users created last week" |
| `INSERT` | INSERT INTO | "Add a new product called Keyboard at $49.99" |
| `UPDATE` | UPDATE | "Change the price of product 5 to $39.99" |
| `DELETE` | DELETE FROM | "Remove all inactive users" |
| `DDL` | CREATE/ALTER/DROP | "Create a table named logs with id and message" |
| `SCHEMA_INFO` | — | "What tables are in the database?" |
| `UNKNOWN` | — | Triggers clarification response |

---

### 6.4 SQL Validation and Safety

Every generated SQL passes through `SQLValidator` before execution:

| Check | Description |
|-------|-------------|
| **Always-blocked keywords** | EXEC, EXECUTE, SHUTDOWN, KILL, LOAD_FILE, INTO OUTFILE, XP_CMDSHELL, SP_EXECUTESQL |
| **Permission check** | Enforces `ENABLE_WRITE_OPERATIONS`, `ENABLE_DELETE_OPERATIONS`, `ENABLE_DDL_OPERATIONS` flags |
| **SQL injection patterns** | 10+ patterns: `OR 1=1`, `--` comments, `UNION SELECT`, `xp_cmdshell`, `WAITFOR DELAY`, `SLEEP()`, statement chaining |
| **Syntax validation** | Uses `sqlparse` to parse and reject multi-statement queries |
| **Strict schema cross-check** | Validates every referenced table and column against live schema; returns suggestions for corrections |
| **NULL comparison check** | Warns on `= NULL` (should be `IS NULL`) |
| **GROUP BY completeness** | Warns on potential missing GROUP BY columns |
| **Complexity check** | Scores JOINs (×10), subqueries (×15), UNIONs (×10), window functions (×5); rejects if score > `MAX_QUERY_COMPLEXITY` |

**Re-reasoning trigger:** If schema cross-check finds missing tables or columns, `requires_re_reasoning=True` is set, causing the graph to route back to `generate_sql` with structured correction hints (up to `MAX_RE_REASONING_ATTEMPTS` = 2 times).

---

### 6.5 Query History

All queries are logged to the `query_history` table with:
- Natural language query text
- Generated SQL
- Classified intent
- Success/failure status
- Error message (if failed)
- Execution time (seconds)
- Result row count
- Timestamp

---

### 6.6 Conversation Memory Management

**Two-tier memory architecture:**

**Tier 1 — Short-term session memory** (in-process, per `thread_id`):
- Current conversation messages (last 10 queries)
- Active database connection info
- Last intent, last SQL, last result count
- Created/updated timestamps

**Tier 2 — Long-term persistent memory** (in-process, per user):
- Schema snapshots (cached schema per connection, 5-min TTL)
- Frequently used query patterns (top 50 per user, by usage count)
- User corrections (last 20 per user)

**Memory API:**

| Endpoint | Description |
|----------|-------------|
| `POST /agent/memory/reset` | Advance nonce to start a fresh conversation thread; clears session from MemoryManager |
| `GET /agent/memory/status` | View current nonce for all user connections |

**Context pruning:**
- `ContextPruner` scores messages by relevance (schema=10, SQL=7, results=6, errors=5, generic=2)
- Always keeps the 4 most recent messages
- Prunes lowest-relevance messages when token budget (3000 tokens) is exceeded
- Triggers summarization when conversation exceeds 20 messages
- Selective clearance: can remove non-schema messages while preserving schema knowledge

---

### 6.7 Database Schema Introspection

| Endpoint | Description |
|----------|-------------|
| `GET /db/tables` | List all tables in the connected database |
| `GET /db/schema/{table_name}` | Get columns, types, PKs, FKs, indexes, row count for a table |
| `POST /db/schema/refresh` | Clear schema cache and force re-inspection |

**Enhanced `SchemaInspector` capabilities:**
- FK relationship graph with BFS-based join path inference (`suggest_join_path()`)
- Fingerprint-based cache invalidation (detects schema changes automatically)
- `validate_references()` for strict table/column grounding
- Fuzzy matching for suggestions when references are invalid
- Dialect-aware type normalization

---

### 6.8 Web Frontend (SPA)

A retro-styled single-page application served at `/` with:
- **Hero section** — scrolling ticker, feature highlights
- **Auth overlay** — login and registration forms
- **Playground section** — natural language query input, results display
- **About section** — project information
- **Dark/Light theme toggle**
- **Connection management UI**
- **Query history panel**

---

## 7. Production-Grade Enhancements (v2)

### 7.1 Hallucination Prevention

**Problem:** The agent fabricated column names, table names, and relationships that did not exist in the actual schema.

**Solution:**
- `SchemaInspector.validate_references()` cross-checks every table and column reference in generated SQL against the live database metadata
- `SQLValidator._strict_schema_check()` extracts table/column references from SQL using regex and validates them
- When schema errors are found, `requires_re_reasoning=True` is set with structured `schema_errors` containing missing objects and fuzzy-match suggestions
- The graph routes back to `generate_sql` with correction hints injected into the prompt
- Maximum 2 re-reasoning attempts before graceful degradation

### 7.2 Agent Stalling and Loop Resolution

**Problem:** The agent got stuck in infinite reasoning loops or halted without producing output.

**Solution:**
- `AgentState.re_reasoning_attempts` counter tracks re-generation cycles
- `route_after_validate_sql()` in `graph.py` checks `re_attempts <= MAX_RE_REASONING_ATTEMPTS`
- When limit is exceeded, routes to END with a clear user-facing error message
- Every node returns a message even on failure (graceful degradation)
- Retry logic in `SQLExecutor` and `NLPProcessor` handles transient API/DB failures

### 7.3 Enhanced Context Window Management

**Problem:** The agent lost critical context mid-conversation or carried irrelevant context.

**Solution:**
- `ContextPruner.prune_messages()` scores messages by relevance and removes lowest-scoring ones when token budget is exceeded
- `ContextPruner.summarize_history()` compresses conversations > 20 messages into dense summaries
- Schema-related messages are never pruned (score = 10, always kept)
- `ContextPruner.clear_non_schema_messages()` enables soft reset without losing schema knowledge
- `MemoryManager` provides `build_memory_context()` for compact context injection

### 7.4 Precise and Accurate SQL Generation

**Problem:** Generated SQL had syntax errors, wrong dialect, and missing edge case handling.

**Solution:**
- **3-pass generation pipeline:**
  - Pass 1: Generate candidate SQL with CoT reasoning
  - Pass 2: Schema-grounded validation and correction (LLM reviews against schema)
  - Pass 3: Performance optimization (only for complex queries with JOINs/subqueries)
- **Dialect-specific rules** for PostgreSQL, MySQL, SQLite, MSSQL, Oracle injected into system prompt
- **Edge case handling:** NULL comparisons, date/time formatting, GROUP BY completeness, subquery aliasing, window functions
- **Schema-grounded prompts:** Only tables/columns from the live schema are referenced

### 7.5 Deeper Query Understanding

**Problem:** The agent failed on complex, multi-intent queries and follow-up questions.

**Solution:**
- `NLPProcessor.classify_intent()` now returns `sub_tasks` for multi-intent decomposition
- `NLPProcessor._resolve_coreferences()` resolves pronouns using conversation history
- Entity extraction infers implicit join conditions from FK relationships in schema context
- CoT reasoning is logged and passed to `SQLGenerator` for context

### 7.6 Structured Chain-of-Thought Reasoning

**Problem:** No visibility into agent reasoning; hard to debug failures.

**Solution:**
- `NLPProcessor` enforces CoT via prompt: "STEP 1 — Identify operation type, STEP 2 — Identify entities, STEP 3 — Detect sub-tasks, STEP 4 — Assess confidence"
- `reasoning` field in `AgentState` carries the CoT output through the pipeline
- `SQLGenerator` receives the reasoning as context for SQL generation
- All nodes log structured debug information

### 7.7 Tool Call Reliability

**Problem:** Tool failures caused silent errors or unhandled exceptions.

**Solution:**
- `_call_groq_with_retry()` in both `NLPProcessor` and `SQLGenerator`: 3 attempts with exponential backoff (1s, 2s, 4s) for transient errors
- `SQLExecutor.execute_query()`: 3 attempts with backoff for transient DB errors
- Error classification: `_classify_error()` distinguishes transient/schema/permission/permanent
- Every tool call has a fallback return value (never raises to the caller)

### 7.8 Persistent Schema and Session Memory

**Problem:** No memory between requests; schema re-fetched on every query.

**Solution:**
- `MemoryManager` provides two-tier memory:
  - **Tier 1 (session):** `SessionMemory` per `thread_id` with last 10 queries
  - **Tier 2 (persistent):** Schema snapshots (5-min TTL), query patterns (top 50/user), corrections (last 20/user)
- Schema snapshots are checked before re-fetching from the database
- Successful query patterns are recorded for future context
- `MemoryManager.build_memory_context()` assembles compact context for LLM prompts

---

## 8. API Reference Summary

### Authentication Routes (`/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | No | Register new user |
| POST | `/auth/login` | No | Login, get JWT token |
| GET | `/auth/me` | Yes | Get current user info |
| GET | `/auth/github/login` | No | GitHub OAuth initiation (placeholder) |
| GET | `/auth/github/callback` | No | GitHub OAuth callback (placeholder) |

### Agent Routes (`/agent`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/agent/query` | Yes | Process natural language query |
| GET | `/agent/history` | Yes | Get query history |
| POST | `/agent/memory/reset` | Yes | Reset conversation memory |
| GET | `/agent/memory/status` | Yes | Get session nonce status |

### Connection Routes (`/connections`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/connections/test` | Yes | Test connection URL |
| POST | `/connections/add` | Yes | Add new connection |
| GET | `/connections/list` | Yes | List all connections |
| PATCH | `/connections/{id}` | Yes | Update connection |
| DELETE | `/connections/{id}` | Yes | Delete connection |

### Database Routes (`/db`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/db/tables` | Yes | List all tables |
| GET | `/db/schema/{table_name}` | Yes | Get table schema |
| POST | `/db/schema/refresh` | Yes | Refresh schema cache |

### System Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Serve frontend SPA |
| GET | `/health` | No | Health check |
| GET | `/docs` | No | Swagger UI |
| GET | `/redoc` | No | ReDoc UI |

---

## 9. Data Models

### `users` Table

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | Integer | PK, auto-increment |
| `email` | String | UNIQUE, NOT NULL, indexed |
| `username` | String | UNIQUE, NOT NULL, indexed |
| `hashed_password` | String | NOT NULL |
| `is_active` | Boolean | default=True |
| `created_at` | DateTime | server_default=now() |

### `user_connections` Table

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | Integer | PK, auto-increment |
| `user_id` | Integer | FK → users.id, NOT NULL |
| `connection_name` | String(255) | NOT NULL |
| `connection_url` | Text | NOT NULL (Fernet-encrypted) |
| `is_active` | Boolean | default=True |
| `is_default` | Boolean | default=False |
| `created_at` | DateTime | server_default=now() |
| `last_used_at` | DateTime | nullable |

### `query_history` Table

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | Integer | PK, auto-increment |
| `user_id` | Integer | FK → users.id, NOT NULL |
| `natural_language_query` | Text | NOT NULL |
| `generated_sql` | Text | nullable |
| `intent` | String | nullable |
| `success` | Boolean | NOT NULL |
| `error_message` | Text | nullable |
| `execution_time` | Float | nullable |
| `result_count` | Integer | nullable |
| `created_at` | DateTime | server_default=now() |

### `AgentState` (LangGraph in-memory)

| Field | Type | Description |
|-------|------|-------------|
| `query` | str | Original natural language query |
| `resolved_query` | str | After coreference resolution |
| `intent` | str | QUERY/INSERT/UPDATE/DELETE/DDL/SCHEMA_INFO/UNKNOWN |
| `intent_confidence` | float | 0.0–1.0 confidence score |
| `entities` | Dict | Tables, columns, conditions, aggregations |
| `reasoning` | str | CoT reasoning steps from NLP |
| `sub_tasks` | List | Ordered sub-tasks for compound queries |
| `sql_query` | Optional[str] | Generated SQL |
| `dialect` | str | postgresql/mysql/sqlite/mssql/oracle |
| `schema_errors` | Dict | Missing tables/columns with suggestions |
| `requires_re_reasoning` | bool | Trigger SQL re-generation |
| `re_reasoning_attempts` | int | Loop detection counter |
| `sql_results` | Optional[List[Dict]] | Query execution results |
| `execution_error_type` | Optional[str] | transient/schema/permission/permanent |
| `error` | Optional[str] | Error message |
| `messages` | List | Conversation history (LangGraph add_messages) |
| `memory_context` | str | Assembled from MemoryManager |
| `db_connection_id` | Optional[int] | Target connection ID |
| `schema_context` | str | Pre-fetched schema for LLM context |

---

## 10. Security Requirements

| Requirement | Implementation |
|-------------|----------------|
| **Password hashing** | `bcrypt` via `passlib[bcrypt]` |
| **JWT authentication** | `python-jose[cryptography]`, HS256, configurable expiry |
| **Connection URL encryption** | Fernet symmetric encryption (`cryptography` library) |
| **SQL injection prevention** | 10+ pattern-based detection in `SQLValidator._check_sql_injection()` |
| **Always-blocked operations** | EXEC, SHUTDOWN, KILL, LOAD_FILE, XP_CMDSHELL, INTO OUTFILE |
| **Operation permissions** | Configurable flags: `ENABLE_WRITE_OPERATIONS`, `ENABLE_DELETE_OPERATIONS`, `ENABLE_DDL_OPERATIONS` |
| **Multi-statement blocking** | `sqlparse` rejects queries with more than one statement |
| **NULL injection prevention** | Warns on `= NULL` patterns |
| **CORS** | Configurable `ALLOWED_ORIGINS` list |
| **Secrets management** | All secrets via environment variables / `.env` file |

**Default security posture:**
- Write operations (INSERT, UPDATE): **ENABLED**
- Delete operations (DELETE): **DISABLED**
- DDL operations (CREATE, ALTER, DROP): **DISABLED**

---

## 11. Configuration and Environment

All configuration is managed via environment variables (loaded from `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./sql_agent.db` | App database URL |
| `SECRET_KEY` | *(change in prod)* | JWT signing key |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT expiry |
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `GROQ_MODEL` | `llama3-70b-8192` | Groq model name |
| `APP_NAME` | `AI SQL Agent` | Application name |
| `DEBUG` | `True` | Debug mode |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:8000` | CORS origins |
| `MAX_QUERY_COMPLEXITY` | `100` | Max SQL complexity score |
| `QUERY_TIMEOUT_SECONDS` | `30` | Query execution timeout |
| `ENABLE_WRITE_OPERATIONS` | `True` | Allow INSERT/UPDATE |
| `ENABLE_DELETE_OPERATIONS` | `False` | Allow DELETE |
| `ENABLE_DDL_OPERATIONS` | `False` | Allow CREATE/ALTER/DROP |
| `CONNECTION_ENCRYPTION_KEY` | *(auto-generated)* | Fernet key for connection URLs |
| `GITHUB_CLIENT_ID` | *(optional)* | GitHub OAuth client ID |
| `GITHUB_CLIENT_SECRET` | *(optional)* | GitHub OAuth client secret |
| `GITHUB_REDIRECT_URI` | `http://localhost:8000/auth/github/callback` | GitHub OAuth redirect |

---

## 12. Non-Functional Requirements

### Performance
- Schema inspection results are **fingerprint-cached** per `SchemaInspector` instance
- Schema snapshots are **cached in `MemoryManager`** with 5-minute TTL (avoids re-fetching on every request)
- Database engines are **pooled** (`pool_size=5`, `max_overflow=10`, `pool_recycle=3600`)
- Dead engines are detected via `pool_pre_ping=True` and recreated automatically
- Query results are **capped at 10,000 rows** to prevent memory exhaustion
- SQL generation uses **3 LLM calls** (pass 1 + pass 2 + optional pass 3 for complex queries)

### Scalability
- Stateless FastAPI server; horizontal scaling is possible
- LangGraph `MemorySaver` is in-process memory — not suitable for multi-instance deployments without a shared checkpoint store
- `MemoryManager` is in-process — not suitable for multi-instance without Redis backend

### Reliability
- All query executions are wrapped in SQLAlchemy transactions
- Errors at any pipeline stage are caught, logged, and returned as structured responses
- Retry logic with exponential backoff for transient Groq API and database errors
- Loop detection prevents infinite re-reasoning cycles
- Application startup initializes the database schema automatically

### Observability
- Structured logging via `app/utils/logger.py` using Python's `logging` module
- Request/response logging middleware (`log_requests_middleware`)
- Error handler middleware (`error_handler_middleware`)
- Health check endpoint at `GET /health`
- All agent nodes log intent, confidence, SQL, and error details

### Testing
- Unit tests: `tests/test_agent.py`, `tests/test_auth.py`
- Integration tests: `tests/test_integration.py`
- Test runner: `pytest` with `pytest-asyncio` and `httpx`
- Coverage configured via `pyproject.toml`

---

## 13. Known Limitations and Future Work

### Current Limitations

| Limitation | Description |
|------------|-------------|
| **In-memory conversation state** | `MemorySaver` and `MemoryManager` are not persistent across server restarts or multi-instance deployments |
| **Query timeout is advisory** | Timeout is logged but not enforced via async cancellation |
| **GitHub OAuth is a placeholder** | Endpoints exist but OAuth flow is not implemented |
| **Single LLM provider** | Only Groq is supported; no fallback or provider abstraction |
| **No rate limiting** | No per-user or global rate limiting on API endpoints |
| **No result pagination** | Query results are returned in full (capped at 10,000 rows) |
| **DDL disabled by default** | CREATE/ALTER/DROP require explicit configuration to enable |
| **Schema cache is per-instance** | Not shared across multiple server instances |

### Recommended Future Enhancements

| Enhancement | Priority | Description |
|-------------|----------|-------------|
| **Persistent LangGraph checkpointer** | High | Replace `MemorySaver` with Redis or PostgreSQL-backed checkpointer |
| **Redis-backed MemoryManager** | High | Move schema cache and patterns to Redis for multi-instance support |
| **Real query timeout enforcement** | High | Use `asyncio.wait_for` or database-level statement timeout |
| **GitHub OAuth implementation** | Medium | Complete the OAuth flow for social login |
| **Result pagination** | Medium | Add `limit`/`offset` to query results in `AgentQueryResponse` |
| **Rate limiting** | Medium | Add `slowapi` or similar middleware for per-user rate limits |
| **Multi-LLM provider support** | Medium | Abstract LLM calls to support OpenAI, Anthropic, local models |
| **Query confirmation flow** | Medium | Implement `sql_requires_confirmation` flag for destructive operations |
| **Streaming responses** | Low | Stream LLM output and query results via Server-Sent Events |
| **Alembic migrations** | Low | Replace `init_db()` with proper Alembic migration management |
| **Frontend framework** | Low | Migrate from vanilla JS to React/Vue for better maintainability |

---

## Appendix: Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Web Framework | FastAPI | ≥0.110.0 |
| ASGI Server | Uvicorn | ≥0.27.0 |
| ORM | SQLAlchemy | ≥2.0.25 |
| Schema Validation | Pydantic v2 | ≥2.6.0 |
| LLM Provider | Groq (Llama 3 70B) | ≥0.4.0 |
| Agent Orchestration | LangGraph | ≥0.0.10 |
| LLM Integration | LangChain-Groq | ≥0.0.1 |
| Authentication | python-jose + passlib | ≥3.3.0 / ≥1.7.4 |
| Encryption | cryptography (Fernet) | ≥41.0.0 |
| SQL Parsing | sqlparse | ≥0.4.4 |
| App Database | SQLite (default) / PostgreSQL | — |
| Testing | pytest + pytest-asyncio + httpx | ≥8.0.0 |
| Frontend | Vanilla HTML/CSS/JS | — |

---

## Appendix: v2 File Change Summary

| File | Change Type | Summary |
|------|-------------|---------|
| `app/core/agent/schema_inspector.py` | **Rewritten** | FK graph, fingerprint cache, `validate_references()`, `suggest_join_path()`, dialect detection |
| `app/core/agent/nlp_processor.py` | **Rewritten** | CoT enforcement, coreference resolution, multi-intent decomposition, retry logic |
| `app/core/agent/sql_generator.py` | **Rewritten** | 3-pass generation, dialect rules, schema-grounded prompts, retry logic |
| `app/core/agent/validator.py` | **Rewritten** | Strict schema cross-check, re-reasoning triggers, expanded injection patterns, NULL/GROUP BY checks |
| `app/core/agent/executor.py` | **Rewritten** | Retry with backoff, error classification, result size cap, improved formatting |
| `app/core/agent/state.py` | **Extended** | 10 new fields: `resolved_query`, `intent_confidence`, `reasoning`, `sub_tasks`, `dialect`, `schema_errors`, `requires_re_reasoning`, `re_reasoning_attempts`, `execution_error_type`, `memory_context` |
| `app/core/agent/nodes.py` | **Rewritten** | CoT reasoning, schema-grounded generation, re-reasoning loop, memory integration, graceful degradation |
| `app/core/agent/graph.py` | **Rewritten** | Loop detection, re-reasoning routing, fallback escalation, memory-integrated SessionManager |
| `app/core/agent/memory_manager.py` | **New** | Two-tier memory: session + schema snapshots + query patterns + corrections |
| `app/core/agent/context_pruner.py` | **New** | Relevance scoring, selective pruning, summarization, token budget management |
| `app/api/routes/agent.py` | **Updated** | Schema cache integration, session memory, new state fields, `finally` block for context var reset |
| `app/core/agent/__init__.py` | **Updated** | Module documentation |
| `plans/PRD.md` | **Updated** | Full v2 documentation |

---

*This PRD was generated from full source code analysis and reflects the production-grade v2 upgrade of the `sql_agent_backend` project.*
