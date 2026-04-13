"""
log_config.py — Centralised logging configuration.

All modules import `get_logger(__name__)` to get a child logger.
Logs are written to:
  • Console  (coloured, concise)
  • app.log  (detailed, with timestamps — for real-time tailing)
  • In-memory ring buffer (for SSE live streaming to the web UI)

Usage in any module:
    from log_config import get_logger
    log = get_logger(__name__)
    log.info("Server started on port %s", port)
"""

import logging
import sys
import threading
import time
from collections import deque
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ── Paths ─────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent
LOG_FILE = LOG_DIR / "app.log"

# ── Formatters ────────────────────────────────────────────────────────
FILE_FMT = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
CONSOLE_FMT = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
    datefmt="%H:%M:%S",
)

# Short format for the UI live-log panel
UI_FMT = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


# ── In-memory ring buffer handler (for SSE streaming) ────────────────
class RingBufferHandler(logging.Handler):
    """Keep the last N log records in a deque for live UI streaming."""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self.buffer: deque[dict] = deque(maxlen=capacity)
        self._seq = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                "seq": self._seq,
                "ts": self.format(record),
                "level": record.levelname,
                "logger": record.name.replace("agent_app.", ""),
                "message": record.getMessage(),
                "time": time.time(),
            }
            with self._lock:
                self.buffer.append(entry)
                self._seq += 1
        except Exception:
            self.handleError(record)

    def get_since(self, after_seq: int = -1) -> list[dict]:
        """Return all entries with seq > after_seq."""
        with self._lock:
            return [e for e in self.buffer if e["seq"] > after_seq]


# ── Root logger setup (runs once on first import) ────────────────────
_root = logging.getLogger("agent_app")
_root.setLevel(logging.DEBUG)

# Singleton ring buffer — importable by app.py for SSE
ring_handler = RingBufferHandler(capacity=500)
ring_handler.setLevel(logging.DEBUG)
ring_handler.setFormatter(UI_FMT)

if not _root.handlers:
    # File handler — rotating, 5 MB × 3 backups, flush on every write
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(FILE_FMT)
    _root.addHandler(fh)

    # Console handler — INFO and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(CONSOLE_FMT)
    _root.addHandler(ch)

    # Ring buffer handler — for web UI live log
    _root.addHandler(ring_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'agent_app' hierarchy."""
    return _root.getChild(name)
