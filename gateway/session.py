"""
gateway/session.py — Multi-user session manager.

Provides conversation isolation per user/channel with TTL-based expiry.
Backends:
  • In-memory dict (default, suitable for single-server / dev)
  • Can be extended to Redis or SQLite for persistence

Each session holds:
  • Conversation history (messages)
  • User metadata (id, channel, created_at)
  • Last-active timestamp for TTL expiry
"""

import time
import uuid
import threading
from dataclasses import dataclass, field
from log_config import get_logger

log = get_logger("session")


@dataclass
class Session:
    """A single user conversation session."""
    session_id: str
    user_id: str
    channel: str                          # "webchat" | "whatsapp" | "slack" | "cli"
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    history: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def touch(self):
        """Update last_active timestamp."""
        self.last_active = time.time()

    def add_message(self, role: str, content: str, **extra):
        """Append a message to conversation history."""
        msg = {"role": role, "content": content, "ts": time.time(), **extra}
        self.history.append(msg)
        self.touch()
        return msg

    def get_messages(self, last_n: int = 0) -> list[dict]:
        """Return conversation history, optionally limited to last N."""
        if last_n > 0:
            return self.history[-last_n:]
        return list(self.history)

    def clear_history(self):
        """Clear conversation history."""
        self.history.clear()
        self.touch()

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_active

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "message_count": len(self.history),
            "age_seconds": round(self.age_seconds, 1),
            "idle_seconds": round(self.idle_seconds, 1),
        }


class SessionManager:
    """
    In-memory session store with TTL-based expiry.

    Thread-safe. Runs a background cleanup thread to evict stale sessions.
    """

    def __init__(self, ttl: int = 1800, cleanup_interval: int = 60):
        """
        Args:
            ttl: Session timeout in seconds (default 30 min).
            cleanup_interval: How often to sweep stale sessions (seconds).
        """
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self.ttl = ttl
        self._cleanup_interval = cleanup_interval
        self._cleanup_thread: threading.Thread | None = None
        self._running = False
        log.info("SessionManager init  ttl=%ds  cleanup=%ds", ttl, cleanup_interval)

    def start_cleanup(self):
        """Start background cleanup thread."""
        if self._running:
            return
        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="session-cleanup"
        )
        self._cleanup_thread.start()
        log.info("Session cleanup thread started")

    def stop_cleanup(self):
        """Stop background cleanup thread."""
        self._running = False

    def _cleanup_loop(self):
        while self._running:
            time.sleep(self._cleanup_interval)
            self._evict_stale()

    def _evict_stale(self):
        """Remove sessions that have been idle longer than TTL."""
        now = time.time()
        with self._lock:
            stale = [
                sid for sid, s in self._sessions.items()
                if (now - s.last_active) > self.ttl
            ]
            for sid in stale:
                del self._sessions[sid]
            if stale:
                log.info("Evicted %d stale session(s)", len(stale))

    # ── CRUD ──────────────────────────────────────────────────────────

    def create_session(
        self,
        user_id: str = "",
        channel: str = "webchat",
        session_id: str = "",
        metadata: dict | None = None,
    ) -> Session:
        """Create a new session and return it."""
        sid = session_id or f"ses_{uuid.uuid4().hex[:12]}"
        uid = user_id or f"anon_{uuid.uuid4().hex[:8]}"
        session = Session(
            session_id=sid,
            user_id=uid,
            channel=channel,
            metadata=metadata or {},
        )
        with self._lock:
            self._sessions[sid] = session
        log.info("Session created: %s  user=%s  channel=%s", sid, uid, channel)
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Retrieve a session by ID, or None if not found / expired."""
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.idle_seconds > self.ttl:
            self.delete_session(session_id)
            return None
        return session

    def get_or_create(
        self,
        session_id: str = "",
        user_id: str = "",
        channel: str = "webchat",
    ) -> Session:
        """Get existing session or create a new one."""
        if session_id:
            session = self.get_session(session_id)
            if session:
                session.touch()
                return session
        return self.create_session(
            user_id=user_id, channel=channel, session_id=session_id
        )

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if found."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                log.info("Session deleted: %s", session_id)
                return True
        return False

    def list_sessions(self) -> list[dict]:
        """Return summary of all active sessions."""
        with self._lock:
            return [s.to_dict() for s in self._sessions.values()]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
