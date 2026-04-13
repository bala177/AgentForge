"""
runtime/memory.py — Persistent Agent Memory (SQLite-backed).

Provides three tiers of memory for the agent:

  1. **Conversation history** — per-session message log (user + assistant turns).
     Used to give the LLM multi-turn context within one chat session.

  2. **Facts / Knowledge** — extracted key facts the agent should remember
     long-term (e.g. "User prefers metric units", "User's city is Tokyo").
     Survives across sessions.

  3. **Tool results cache** — recent tool call → result pairs to avoid
     redundant calls (e.g. same weather query within 5 minutes).

All data is stored in a single SQLite file (`memory.db`) alongside the app.
Thread-safe via SQLite's WAL mode + Python's `sqlite3` module behaviour.

Usage:
    from runtime.memory import MemoryStore
    mem = MemoryStore()
    mem.add_message("ses_abc123", "user", "What's the weather in Tokyo?")
    mem.add_message("ses_abc123", "assistant", "It's 22°C and sunny.")
    history = mem.get_conversation("ses_abc123", limit=20)
    mem.save_fact("user_city", "Tokyo", source="inferred from weather query")
    mem.cache_tool_result("weather_lookup", "Tokyo", result_json, ttl=300)
"""

import json
import sqlite3
import time
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from log_config import get_logger

log = get_logger("memory")

_DB_PATH = Path(__file__).resolve().parent.parent / "memory.db"


@dataclass
class Message:
    """A single conversation turn."""
    session_id: str
    role: str          # "user" | "assistant" | "system" | "tool"
    content: str
    timestamp: float
    metadata: dict = field(default_factory=dict)


@dataclass
class Fact:
    """A persistent knowledge fact."""
    key: str
    value: str
    source: str = ""
    created: float = 0.0
    updated: float = 0.0


class MemoryStore:
    """SQLite-backed agent memory with conversation, facts, and tool cache."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(_DB_PATH)
        self._local = threading.local()
        self._init_db()
        log.info("MemoryStore initialised  db=%s", self._db_path)

    # ── Connection management (thread-local) ──────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local connection (created on first access)."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT    NOT NULL,
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                timestamp   REAL    NOT NULL,
                metadata    TEXT    DEFAULT '{}',
                UNIQUE(session_id, timestamp, role)
            );

            CREATE INDEX IF NOT EXISTS idx_conv_session
                ON conversations(session_id);

            CREATE TABLE IF NOT EXISTS facts (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                source      TEXT DEFAULT '',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_cache (
                cache_key   TEXT PRIMARY KEY,
                tool_name   TEXT NOT NULL,
                tool_input  TEXT NOT NULL,
                result      TEXT NOT NULL,
                cached_at   REAL NOT NULL,
                expires_at  REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cache_expires
                ON tool_cache(expires_at);
        """)
        conn.commit()
        log.debug("Memory tables verified")

    # ==================================================================
    #  1. Conversation History
    # ==================================================================

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ):
        """Append a message to the conversation log."""
        now = time.time()
        meta_json = json.dumps(metadata or {})
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO conversations "
                "(session_id, role, content, timestamp, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, now, meta_json),
            )
            conn.commit()
        except sqlite3.Error as e:
            log.error("Failed to add message: %s", e)

    def get_conversation(
        self,
        session_id: str,
        limit: int = 50,
        since: Optional[float] = None,
    ) -> list[Message]:
        """Retrieve conversation history for a session, most recent last."""
        conn = self._get_conn()
        if since:
            rows = conn.execute(
                "SELECT session_id, role, content, timestamp, metadata "
                "FROM conversations "
                "WHERE session_id = ? AND timestamp >= ? "
                "ORDER BY timestamp ASC LIMIT ?",
                (session_id, since, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT session_id, role, content, timestamp, metadata "
                "FROM conversations "
                "WHERE session_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            rows = list(reversed(rows))  # return in chronological order

        return [
            Message(
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                timestamp=r["timestamp"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]

    def get_session_ids(self, limit: int = 100) -> list[str]:
        """Get distinct session IDs, most recent first."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT session_id, MAX(timestamp) as last_ts "
            "FROM conversations "
            "GROUP BY session_id "
            "ORDER BY last_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [r["session_id"] for r in rows]

    def delete_conversation(self, session_id: str) -> int:
        """Delete all messages for a session. Returns count deleted."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM conversations WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        deleted = cursor.rowcount
        log.info("Deleted %d messages for session %s", deleted, session_id)
        return deleted

    def conversation_summary(self, session_id: str) -> dict:
        """Get stats about a conversation."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as count, "
            "MIN(timestamp) as first_ts, "
            "MAX(timestamp) as last_ts "
            "FROM conversations WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return {
            "session_id": session_id,
            "message_count": row["count"],
            "first_message": row["first_ts"],
            "last_message": row["last_ts"],
        }

    def count_messages(self, session_id: str) -> int:
        """Count total messages stored for a session."""
        conn = self._get_conn()
        return conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE session_id = ?", (session_id,)
        ).fetchone()[0]

    def trim_to_last_n(self, session_id: str, n: int = 5) -> int:
        """Keep only the last N messages for a session. Returns count deleted."""
        conn = self._get_conn()
        keep_ids = conn.execute(
            "SELECT id FROM conversations WHERE session_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (session_id, n),
        ).fetchall()
        if not keep_ids:
            return 0
        ids_to_keep = tuple(r[0] for r in keep_ids)
        placeholders = ",".join("?" * len(ids_to_keep))
        cursor = conn.execute(
            f"DELETE FROM conversations WHERE session_id = ? AND id NOT IN ({placeholders})",
            (session_id, *ids_to_keep),
        )
        conn.commit()
        deleted = cursor.rowcount
        log.info("Trimmed session %s: deleted %d messages, kept %d", session_id, deleted, n)
        return deleted

    def consolidate(self, session_id: str, llm_fn) -> str:
        """Summarize conversation via LLM, write to MEMORY.md, trim to last 5 messages.

        Args:
            session_id: The session to compact.
            llm_fn: Callable(prompt: str) -> str — calls the LLM for summarisation.

        Returns:
            The summary text, or an error message.
        """
        msgs = self.get_conversation(session_id, limit=30)
        if len(msgs) < 5:
            return "Session is already compact (fewer than 5 messages)."
        dialogue = "\n".join(
            f"[{m.role.upper()}]: {m.content[:300]}" for m in msgs
        )
        prompt = (
            "Summarize this conversation into concise bullet-point facts "
            "the agent should remember going forward. Be brief — 5 to 10 bullets max.\n\n"
            + dialogue
        )
        try:
            summary = llm_fn(prompt)
        except Exception as e:
            summary = f"(Compaction failed: {e})"
        # Append to MEMORY.md (readable by agent via file_manager tool)
        memory_md = Path(__file__).parent / "MEMORY.md"
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(memory_md, "a", encoding="utf-8") as f:
            f.write(f"\n## Session {session_id[:16]} — {ts}\n{summary}\n")
        # Also persist as a searchable fact
        self.save_fact(f"summary_{session_id[:16]}", summary[:500], source="auto_compact")
        trimmed = self.trim_to_last_n(session_id, n=5)
        log.info(
            "Consolidated session %s: wrote MEMORY.md, trimmed %d messages",
            session_id, trimmed,
        )
        return summary

    # ==================================================================
    #  2. Facts / Knowledge Store
    # ==================================================================

    def save_fact(self, key: str, value: str, source: str = ""):
        """Save or update a persistent fact."""
        now = time.time()
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT created_at FROM facts WHERE key = ?", (key,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE facts SET value = ?, source = ?, updated_at = ? "
                "WHERE key = ?",
                (value, source, now, key),
            )
        else:
            conn.execute(
                "INSERT INTO facts (key, value, source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, value, source, now, now),
            )
        conn.commit()
        log.debug("Fact saved: %s = %s", key, value[:100])

    def get_fact(self, key: str) -> Optional[Fact]:
        """Retrieve a single fact by key."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT key, value, source, created_at, updated_at "
            "FROM facts WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        return Fact(
            key=row["key"],
            value=row["value"],
            source=row["source"],
            created=row["created_at"],
            updated=row["updated_at"],
        )

    def search_facts(self, query: str = "", limit: int = 50) -> list[Fact]:
        """Search facts by key or value (LIKE match). Empty query returns all."""
        conn = self._get_conn()
        if query:
            pattern = f"%{query}%"
            rows = conn.execute(
                "SELECT key, value, source, created_at, updated_at "
                "FROM facts "
                "WHERE key LIKE ? OR value LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, value, source, created_at, updated_at "
                "FROM facts ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Fact(
                key=r["key"], value=r["value"], source=r["source"],
                created=r["created_at"], updated=r["updated_at"],
            )
            for r in rows
        ]

    def delete_fact(self, key: str) -> bool:
        """Delete a fact. Returns True if it existed."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM facts WHERE key = ?", (key,))
        conn.commit()
        return cursor.rowcount > 0

    def all_facts_as_context(self, limit: int = 30) -> str:
        """Format all facts as a string for injecting into LLM context."""
        facts = self.search_facts("", limit=limit)
        if not facts:
            return ""
        lines = ["Known facts about the user/context:"]
        for f in facts:
            lines.append(f"  - {f.key}: {f.value}")
        return "\n".join(lines)

    # ==================================================================
    #  Conversation Management
    # ==================================================================

    def clear_conversation(self, session_id: str) -> int:
        """Delete all conversation messages for a session. Returns count deleted."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM conversations WHERE session_id = ?", (session_id,)
        )
        conn.commit()
        count = cursor.rowcount
        log.info("Cleared %d messages for session %s", count, session_id)
        return count

    # ==================================================================
    #  3. Tool Results Cache
    # ==================================================================

    def cache_tool_result(
        self,
        tool_name: str,
        tool_input: str,
        result: str,
        ttl: int = 300,
    ):
        """Cache a tool result. TTL in seconds (default 5 min)."""
        now = time.time()
        cache_key = f"{tool_name}::{tool_input}"
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO tool_cache "
            "(cache_key, tool_name, tool_input, result, cached_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cache_key, tool_name, tool_input, result, now, now + ttl),
        )
        conn.commit()

    def get_cached_result(self, tool_name: str, tool_input: str) -> Optional[str]:
        """Get a cached tool result if still valid. Returns None if expired/missing."""
        cache_key = f"{tool_name}::{tool_input}"
        conn = self._get_conn()
        row = conn.execute(
            "SELECT result, expires_at FROM tool_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] < time.time():
            # Expired — delete it
            conn.execute("DELETE FROM tool_cache WHERE cache_key = ?", (cache_key,))
            conn.commit()
            return None
        return row["result"]

    def clear_expired_cache(self) -> int:
        """Remove all expired cache entries. Returns count deleted."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM tool_cache WHERE expires_at < ?", (time.time(),)
        )
        conn.commit()
        return cursor.rowcount

    # ==================================================================
    #  Utility
    # ==================================================================

    def stats(self) -> dict:
        """Overall memory statistics."""
        conn = self._get_conn()
        conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        session_count = conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM conversations"
        ).fetchone()[0]
        fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        cache_count = conn.execute(
            "SELECT COUNT(*) FROM tool_cache WHERE expires_at >= ?",
            (time.time(),),
        ).fetchone()[0]
        return {
            "total_messages": conv_count,
            "total_sessions": session_count,
            "total_facts": fact_count,
            "active_cache_entries": cache_count,
            "db_path": self._db_path,
        }

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
