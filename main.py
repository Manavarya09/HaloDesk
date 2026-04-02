#!/usr/bin/env python3
"""HaloDesk main entry point.

Usage:
    python main.py                  # interactive CLI
    python main.py --once "query"   # single-shot mode
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from memory.sqlite_store import SQLiteStore
from memory.faiss_retriever import FAISSRetriever
from tools import ToolRegistry
from tools.linkup_client import LinkupSearchTool
from tools.email_adapter import ListEmailsTool, ReadEmailTool, DraftReplyTool
from tools.document_adapter import ReadDocumentTool, ListDocumentsTool, SummarizeDocumentTool
from tools.calendar_adapter import ListEventsTool, CreateEventTool, CreateReminderTool
from tools.memory_tools import MemoryStoreTool, MemoryRecallTool
from agent.loop import AgentLoop

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT)
    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #

def bootstrap(cfg: dict) -> AgentLoop:
    """Wire up all components and return a ready-to-use AgentLoop."""

    # Memory
    db = SQLiteStore(cfg["memory"]["sqlite_path"])
    faiss = FAISSRetriever(cfg["memory"])

    # Tool registry
    registry = ToolRegistry()

    # Linkup (web research)
    registry.register(LinkupSearchTool(cfg.get("linkup", {})))

    # Email tools
    email_cfg = cfg.get("email", {})
    registry.register(ListEmailsTool(email_cfg))
    registry.register(ReadEmailTool(email_cfg))
    registry.register(DraftReplyTool())

    # Document tools
    doc_cfg = cfg.get("documents", {})
    registry.register(ReadDocumentTool())
    registry.register(ListDocumentsTool(doc_cfg))
    registry.register(SummarizeDocumentTool())

    # Calendar tools
    cal_cfg = cfg.get("calendar", {})
    registry.register(ListEventsTool(cal_cfg))
    registry.register(CreateEventTool(cal_cfg))
    registry.register(CreateReminderTool(cal_cfg))

    # Memory tools
    registry.register(MemoryStoreTool(db, faiss))
    registry.register(MemoryRecallTool(db, faiss))

    print(f"✓ Registered {len(registry.names())} tools: {', '.join(registry.names())}")

    return AgentLoop(cfg, registry, db, faiss)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║                       HaloDesk                          ║
║                                                          ║
║  Commands:                                               ║
║    /tools   - list available tools                       ║
║    /memory  - show recent memory                         ║
║    /tasks   - show recent tasks                          ║
║    /quit    - exit                                       ║
╚══════════════════════════════════════════════════════════╝
"""


def run_interactive(agent: AgentLoop):
    """Interactive REPL."""
    print(BANNER)
    print(f"Session: {agent.session_id}\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Meta-commands
        if user_input.lower() in ("/quit", "/exit", "/q"):
            print("Goodbye!")
            break
        if user_input.lower() == "/tools":
            for t in agent._registry.all_tools():
                print(f"  • {t.name}: {t.description[:80]}")
            continue
        if user_input.lower() == "/memory":
            memories = agent._faiss.search("recent activity", top_k=5)
            if memories:
                for m in memories:
                    print(f"  [{m.get('source', '?')}] {m.get('text', '')[:100]}")
            else:
                print("  (no memories stored yet)")
            continue
        if user_input.lower() == "/tasks":
            tasks = agent._db.recent_tasks(agent.session_id, limit=5)
            if tasks:
                for t in tasks:
                    print(f"  [{t['status']}] {t['goal'][:80]}")
            else:
                print("  (no tasks yet)")
            continue

        # Normal agent query
        try:
            response = agent.run(user_input)
            print(f"\nAgent > {response}\n")
        except Exception as exc:
            logging.getLogger(__name__).error("Agent error: %s", exc, exc_info=True)
            print(f"\n[Error] {exc}\n")


def main():
    parser = argparse.ArgumentParser(description="HaloDesk")
    parser.add_argument("--config", type=str, help="Path to override config YAML")
    parser.add_argument("--once", type=str, help="Run a single query and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)
    cfg = load_config(args.config)
    agent = bootstrap(cfg)

    if args.once:
        response = agent.run(args.once)
        print(response)
    else:
        run_interactive(agent)


if __name__ == "__main__":
    main()
