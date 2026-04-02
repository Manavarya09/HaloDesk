"""Memory tools — allow the agent to store and recall facts and context."""

from __future__ import annotations

import json
import logging
from typing import Any

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class MemoryStoreTool(BaseTool):
    """Store an important fact or decision in long-term memory."""

    def __init__(self, sqlite_store, faiss_retriever):
        self._db = sqlite_store
        self._faiss = faiss_retriever

    @property
    def name(self) -> str:
        return "memory_store"

    @property
    def description(self) -> str:
        return (
            "Store an important fact, decision, or piece of information in the agent's "
            "long-term memory for future recall."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact or information to remember."},
                "source": {"type": "string", "description": "Where this came from (e.g. 'email', 'document', 'user', 'linkup')."},
            },
            "required": ["content"],
        }

    def run(self, **kwargs) -> ToolResult:
        content = kwargs.get("content", "")
        source = kwargs.get("source", "agent")
        if not content.strip():
            return ToolResult(success=False, error="Empty content — nothing to store.")
        embedding_id = self._faiss.add(content, source=source)
        self._db.store_fact(content, source=source, embedding_id=embedding_id)
        logger.info("Stored fact (source=%s): %s", source, content[:80])
        return ToolResult(success=True, data=f"Fact stored in memory (source: {source}).")


class MemoryRecallTool(BaseTool):
    """Recall relevant facts from long-term memory by semantic similarity."""

    def __init__(self, sqlite_store, faiss_retriever):
        self._db = sqlite_store
        self._faiss = faiss_retriever

    @property
    def name(self) -> str:
        return "memory_recall"

    @property
    def description(self) -> str:
        return (
            "Search the agent's long-term memory for facts related to a query. "
            "Use this to resolve references like 'that email', 'the contract', or to "
            "recall prior context."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in memory."},
                "top_k": {"type": "integer", "description": "Max results to return (default 5)."},
            },
            "required": ["query"],
        }

    def run(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "")
        top_k = kwargs.get("top_k", 5)
        if not query.strip():
            return ToolResult(success=False, error="Empty query.")

        # Try semantic search first
        results = self._faiss.search(query, top_k=top_k)

        # Fallback / supplement with keyword search
        if len(results) < top_k:
            kw_results = self._db.search_facts(query.split()[0] if query.split() else query, limit=top_k)
            seen_texts = {r["text"] for r in results}
            for kr in kw_results:
                if kr["content"] not in seen_texts:
                    results.append({"text": kr["content"], "source": kr["source"], "score": 0.0})

        if not results:
            return ToolResult(success=True, data="No relevant memories found.")
        return ToolResult(success=True, data=json.dumps(results[:top_k], indent=2))
