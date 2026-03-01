"""
SQL Agent core modules — Production-Grade v2.

Modules:
- state: AgentState TypedDict
- graph: LangGraph StateGraph with loop detection and fallback escalation
- nodes: Node functions with CoT reasoning and schema grounding
- nlp_processor: Intent classification with coreference resolution
- sql_generator: Multi-pass SQL generation with dialect awareness
- validator: Strict schema cross-checking and injection prevention
- executor: SQL execution with retry and error classification
- schema_inspector: Deep schema introspection with FK graph
- memory_manager: Two-tier memory (session + persistent)
- context_pruner: Selective context pruning and summarization
"""
