"""Linkup agentic search tool.

Wraps Linkup's POST /v1/search endpoint to give the agent real-time web knowledge.
Privacy: only sanitized, non-PII queries are ever sent.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Rate-limiter (simple token-bucket per process)
# --------------------------------------------------------------------------- #

class _RateLimiter:
    def __init__(self, max_per_second: int = 10):
        self._interval = 1.0 / max_per_second
        self._last = 0.0

    def wait(self):
        now = time.monotonic()
        diff = now - self._last
        if diff < self._interval:
            time.sleep(self._interval - diff)
        self._last = time.monotonic()


# --------------------------------------------------------------------------- #
# Tool implementation
# --------------------------------------------------------------------------- #

class LinkupSearchTool(BaseTool):
    """Call Linkup's agentic search API for real-time web knowledge."""

    def __init__(self, cfg: dict):
        self._api_key: str = cfg.get("api_key", "")
        self._base_url: str = cfg.get("base_url", "https://api.linkup.so/v1/search")
        self._default_depth: str = cfg.get("default_depth", "deep")
        self._default_output: str = cfg.get("default_output_type", "searchResults")
        self._limiter = _RateLimiter(cfg.get("rate_limit_per_second", 10))

    # -- BaseTool interface --------------------------------------------------

    @property
    def name(self) -> str:
        return "web_research"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information using Linkup. "
            "Use this when you need to research companies, people, recent events, "
            "fact-check claims, or gather background information. "
            "NEVER include personal/sensitive data in the query."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A concise, specific natural-language search query (no PII).",
                },
                "depth": {
                    "type": "string",
                    "enum": ["standard", "deep"],
                    "description": "Search depth. Use 'deep' for thorough research, 'standard' for quick lookups.",
                },
                "output_type": {
                    "type": "string",
                    "enum": ["searchResults", "sourcedAnswer", "structured"],
                    "description": "Response format. 'searchResults' for raw results, 'sourcedAnswer' for a concise cited answer.",
                },
            },
            "required": ["query"],
        }

    def run(self, **kwargs) -> ToolResult:
        query: str = kwargs.get("query", "")
        depth: str = kwargs.get("depth", self._default_depth)
        output_type: str = kwargs.get("output_type", self._default_output)

        if not query.strip():
            return ToolResult(success=False, error="Empty search query.")

        if not self._api_key:
            return ToolResult(
                success=False,
                error="LINKUP_API_KEY not configured. Set the env var or add it to config.",
            )

        payload = {
            "q": query,
            "depth": depth,
            "outputType": output_type,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            self._limiter.wait()
            logger.info("Linkup search: depth=%s query=%r", depth, query)
            resp = requests.post(self._base_url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return ToolResult(success=True, data=self._format(data, output_type))
        except requests.HTTPError as exc:
            logger.error("Linkup HTTP error: %s", exc)
            return ToolResult(success=False, error=f"Linkup API error: {exc}")
        except Exception as exc:
            logger.error("Linkup request failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _format(data: dict, output_type: str) -> str:
        """Turn raw Linkup JSON into a text block the LLM can consume."""
        if output_type == "sourcedAnswer":
            answer = data.get("answer", "")
            sources = data.get("sources", [])
            parts = [answer]
            if sources:
                parts.append("\nSources:")
                for s in sources[:5]:
                    parts.append(f"  - {s.get('title', '')} ({s.get('url', '')})")
            return "\n".join(parts)

        # searchResults / structured
        results = data.get("results", data.get("items", []))
        if not results:
            return json.dumps(data, indent=2)  # fallback: return raw JSON

        parts: list[str] = []
        for i, r in enumerate(results[:8], 1):
            title = r.get("title") or r.get("name", "")
            snippet = r.get("snippet") or r.get("content", "")
            url = r.get("url", "")
            parts.append(f"[{i}] {title}\n    {snippet}\n    {url}")
        return "\n\n".join(parts)
