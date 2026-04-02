"""SQLite-based memory store for conversation history, tasks, and user preferences."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SQLiteStore:
    """Lightweight wrapper around a local SQLite database for agent memory."""

    def __init__(self, db_path: str = "data/agent.db"):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,     -- 'user', 'assistant', 'tool'
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT,
                goal        TEXT NOT NULL,
                steps_json  TEXT,              -- JSON array of planned steps
                status      TEXT DEFAULT 'pending',  -- pending | running | done | failed
                result      TEXT,
                created_at  TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS facts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                content   TEXT NOT NULL,
                source    TEXT,               -- 'email', 'document', 'linkup', 'user', ...
                embedding_id TEXT,            -- reference to FAISS vector index
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
        """)
        self._conn.commit()

    # ---- Conversations --------------------------------------------------- #

    def add_message(self, session_id: str, role: str, content: str):
        self._conn.execute(
            "INSERT INTO conversations (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.now().isoformat()),
        )
        self._conn.commit()

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT role, content, timestamp FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---- Tasks ----------------------------------------------------------- #

    def create_task(self, session_id: str, goal: str, steps: list[str]) -> int:
        cur = self._conn.execute(
            "INSERT INTO tasks (session_id, goal, steps_json, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (session_id, goal, json.dumps(steps), datetime.now().isoformat()),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_task(self, task_id: int, status: str, result: str | None = None):
        completed = datetime.now().isoformat() if status in ("done", "failed") else None
        self._conn.execute(
            "UPDATE tasks SET status = ?, result = ?, completed_at = COALESCE(?, completed_at) WHERE id = ?",
            (status, result, completed, task_id),
        )
        self._conn.commit()

    def recent_tasks(self, session_id: str, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, goal, status, result, created_at FROM tasks WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Facts / long-term memory ---------------------------------------- #

    def store_fact(self, content: str, source: str = "", embedding_id: str = ""):
        self._conn.execute(
            "INSERT INTO facts (content, source, embedding_id, created_at) VALUES (?, ?, ?, ?)",
            (content, source, embedding_id, datetime.now().isoformat()),
        )
        self._conn.commit()

    def search_facts(self, keyword: str, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT content, source, created_at FROM facts WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Preferences ----------------------------------------------------- #

    def set_pref(self, key: str, value: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO user_preferences (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_pref(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM user_preferences WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def close(self):
        self._conn.close()
