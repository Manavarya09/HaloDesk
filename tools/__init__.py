"""Base tool interface and global tool registry."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Tool result container
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    success: bool
    data: Any = None
    error: str | None = None
    generated_files: list[dict] | None = None  # [{"type": "ics"|"eml", "path": "...", "label": "..."}]

    def __str__(self):
        if self.success:
            return str(self.data)
        return f"[ERROR] {self.error}"


# ---------------------------------------------------------------------------
# Abstract base for every tool
# ---------------------------------------------------------------------------

class BaseTool(ABC):
    """Every tool exposes a name, description (for LLM), parameter schema, and a run() method."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON-schema-style dict describing the function parameters."""
        ...

    @abstractmethod
    def run(self, **kwargs) -> ToolResult: ...

    def as_ollama_tool(self) -> dict:
        """Return the tool definition in Ollama function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class ToolRegistry:
    _tools: dict[str, BaseTool] = field(default_factory=dict)

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def ollama_tool_definitions(self) -> list[dict]:
        return [t.as_ollama_tool() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())
