"""Document tools — read, extract, and search local documents.

Supports PDF (via PyMuPDF), DOCX (python-docx), plain text, and Markdown.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _extract_text(path: Path) -> str:
    """Extract plain text from a supported file type."""
    ext = path.suffix.lower()

    if ext in (".txt", ".md"):
        return path.read_text(errors="replace")

    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            return "\n\n".join(page.get_text() for page in doc)
        except ImportError:
            return "[ERROR] PyMuPDF (fitz) not installed — cannot read PDFs."

    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            return "[ERROR] python-docx not installed — cannot read DOCX files."

    return f"[Unsupported file type: {ext}]"


# =========================================================================== #
#  read_document
# =========================================================================== #

class ReadDocumentTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_document"

    @property
    def description(self) -> str:
        return "Read and extract text content from a local document (PDF, DOCX, TXT, MD)."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative file path to the document.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Truncate output to this many characters (default 8000).",
                },
            },
            "required": ["path"],
        }

    def run(self, **kwargs) -> ToolResult:
        file_path = Path(kwargs["path"]).expanduser()
        max_chars = kwargs.get("max_chars", 8000)

        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        try:
            text = _extract_text(file_path)
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[...truncated at {max_chars} chars]"
            return ToolResult(success=True, data=text)
        except Exception as exc:
            logger.error("read_document failed for %s: %s", file_path, exc)
            return ToolResult(success=False, error=str(exc))


# =========================================================================== #
#  list_documents
# =========================================================================== #

class ListDocumentsTool(BaseTool):
    def __init__(self, cfg: dict):
        self._search_dir = Path(cfg.get("search_directory", "data/documents"))
        self._extensions = set(cfg.get("supported_extensions", [".pdf", ".docx", ".txt", ".md"]))

    @property
    def name(self) -> str:
        return "list_documents"

    @property
    def description(self) -> str:
        return "List available documents in the configured documents directory."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional filename substring filter.",
                },
            },
            "required": [],
        }

    def run(self, **kwargs) -> ToolResult:
        self._search_dir.mkdir(parents=True, exist_ok=True)
        query = (kwargs.get("query") or "").lower()
        found = []
        for p in sorted(self._search_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in self._extensions:
                if query and query not in p.name.lower():
                    continue
                found.append({
                    "path": str(p),
                    "name": p.name,
                    "size_kb": round(p.stat().st_size / 1024, 1),
                })
        return ToolResult(success=True, data=json.dumps(found, indent=2))


# =========================================================================== #
#  summarize_document (delegates to LLM — placeholder for executor)
# =========================================================================== #

class SummarizeDocumentTool(BaseTool):
    """Reads a document and returns its text — the LLM in the agent loop will summarize."""

    @property
    def name(self) -> str:
        return "summarize_document"

    @property
    def description(self) -> str:
        return (
            "Extract text from a document and return it for summarization. "
            "The agent will summarize the extracted content."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the document to summarize.",
                },
            },
            "required": ["path"],
        }

    def run(self, **kwargs) -> ToolResult:
        file_path = Path(kwargs["path"]).expanduser()
        if not file_path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")
        try:
            text = _extract_text(file_path)
            # Limit to 6000 chars for LLM context window
            if len(text) > 6000:
                text = text[:6000] + "\n\n[...truncated for summarization]"
            return ToolResult(success=True, data=text)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
