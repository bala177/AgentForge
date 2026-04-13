"""
activity_store.py — Unified Activity Journal + Enhanced Notes Store.

Two data files:
  • agent_activity.json  — auto-logged tool calls & chat interactions
  • agent_notes.json     — user-created notes (v2 with tags, categories, pin)

Both are JSON-backed with in-memory caching for fast reads.
"""

import json
import time
import datetime
import uuid
from pathlib import Path
from collections import Counter
from log_config import get_logger

log = get_logger("store")

_DIR = Path(__file__).parent
ACTIVITY_FILE = _DIR / "agent_activity.json"
NOTES_FILE = _DIR / "agent_notes.json"


# =====================================================================
#  Helpers
# =====================================================================

def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _make_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}"


def _read_json(path: Path) -> list:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            log.warning("Corrupt JSON in %s — starting fresh", path)
    return []


def _write_json(path: Path, data: list):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# =====================================================================
#  Activity Journal  (auto-logged, append-only)
# =====================================================================

_activity_cache: list[dict] | None = None


def _load_activities() -> list[dict]:
    global _activity_cache
    if _activity_cache is None:
        _activity_cache = _read_json(ACTIVITY_FILE)
    return _activity_cache


def _flush_activities():
    _write_json(ACTIVITY_FILE, _load_activities())


def log_activity(
    *,
    act_type: str,           # "tool" | "chat"
    tool: str = "",
    input_text: str = "",
    output_text: str = "",
    success: bool = True,
    duration_ms: float = 0,
    mode: str = "",
    model: str = "",
    steps: int = 0,
    session_id: str = "",
):
    """Append an activity entry. Called automatically by app.py."""
    entry = {
        "id": _make_id("act"),
        "type": act_type,
        "timestamp": _ts(),
        "tool": tool,
        "input": input_text[:500],
        "output": output_text[:500],
        "success": success,
        "duration_ms": round(duration_ms, 1),
        "mode": mode,
        "model": model,
        "steps": steps,
        "session_id": session_id,
    }
    activities = _load_activities()
    activities.append(entry)
    # Keep max 2000 entries on disk
    if len(activities) > 2000:
        activities[:] = activities[-2000:]
    _flush_activities()
    log.debug("Activity logged: %s %s", act_type, tool)
    return entry


def get_activities(
    act_type: str = "",
    tool: str = "",
    days: int = 0,
    page: int = 1,
    limit: int = 50,
) -> dict:
    """Query activities with optional filters & pagination."""
    items = list(_load_activities())

    # Filters
    if act_type:
        items = [a for a in items if a["type"] == act_type]
    if tool:
        items = [a for a in items if a.get("tool") == tool]
    if days > 0:
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        items = [a for a in items if a["timestamp"] >= cutoff]

    total = len(items)
    # Newest first
    items.reverse()
    start = (page - 1) * limit
    page_items = items[start:start + limit]

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
    }


def get_activity_stats(days: int = 30) -> dict:
    """Aggregated stats for the dashboard."""
    cutoff = ""
    if days > 0:
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")

    items = _load_activities()
    if cutoff:
        items = [a for a in items if a["timestamp"] >= cutoff]

    tool_counter = Counter()
    type_counter = Counter()
    daily_counter = Counter()
    total_duration = 0.0
    success_count = 0

    for a in items:
        type_counter[a["type"]] += 1
        if a.get("tool"):
            tool_counter[a["tool"]] += 1
        day = a["timestamp"][:10]
        daily_counter[day] += 1
        total_duration += a.get("duration_ms", 0)
        if a.get("success"):
            success_count += 1

    total = len(items)
    return {
        "total": total,
        "by_type": dict(type_counter),
        "top_tools": tool_counter.most_common(10),
        "daily": dict(sorted(daily_counter.items())[-14:]),  # last 14 days
        "avg_duration_ms": round(total_duration / max(total, 1), 1),
        "success_rate": round(success_count / max(total, 1) * 100, 1),
        "days": days,
    }


def export_activities(fmt: str = "json") -> str:
    """Export activities as JSON or CSV string."""
    items = _load_activities()
    if fmt == "csv":
        if not items:
            return "id,type,timestamp,tool,input,output,success,duration_ms,mode,model\n"
        keys = ["id", "type", "timestamp", "tool", "input", "output",
                "success", "duration_ms", "mode", "model"]
        lines = [",".join(keys)]
        for a in items:
            row = []
            for k in keys:
                val = str(a.get(k, "")).replace('"', '""')
                row.append(f'"{val}"')
            lines.append(",".join(row))
        return "\n".join(lines)
    return json.dumps(items, indent=2, ensure_ascii=False)


# =====================================================================
#  Notes Store (v2 — user-created, rich metadata)
# =====================================================================

_notes_cache: list[dict] | None = None


def _load_notes() -> list[dict]:
    global _notes_cache
    if _notes_cache is None:
        raw = _read_json(NOTES_FILE)
        _notes_cache = _migrate_notes(raw)
    return _notes_cache


def _flush_notes():
    _write_json(NOTES_FILE, _load_notes())


def _migrate_notes(notes: list[dict]) -> list[dict]:
    """Migrate v1 notes (flat text) to v2 format in-place."""
    changed = False
    for n in notes:
        if "id" not in n:
            n["id"] = _make_id("note")
            changed = True
        if "category" not in n:
            n["category"] = "general"
            changed = True
        if "tags" not in n:
            n["tags"] = []
            changed = True
        if "pinned" not in n:
            n["pinned"] = False
            changed = True
        if "color" not in n:
            n["color"] = "default"
            changed = True
        if "updated" not in n:
            n["updated"] = n.get("created", _ts())
            changed = True
        if "source" not in n:
            n["source"] = "manual"
            changed = True
    if changed and notes:
        _write_json(NOTES_FILE, notes)
        log.info("Migrated %d notes to v2 format", len(notes))
    return notes


def save_note(
    text: str,
    category: str = "general",
    tags: list[str] | None = None,
    color: str = "default",
    source: str = "manual",
) -> dict:
    """Create a new note and return it."""
    now = _ts()
    note = {
        "id": _make_id("note"),
        "text": text,
        "category": category,
        "tags": tags or [],
        "pinned": False,
        "color": color,
        "created": now,
        "updated": now,
        "source": source,
    }
    notes = _load_notes()
    notes.append(note)
    _flush_notes()
    log.info("Note saved: %s (total=%d)", note["id"], len(notes))
    return note


def update_note(note_id: str, **fields) -> dict | None:
    """Update a note by ID. Returns updated note or None."""
    notes = _load_notes()
    for n in notes:
        if n["id"] == note_id:
            for k in ("text", "category", "tags", "color", "pinned"):
                if k in fields:
                    n[k] = fields[k]
            n["updated"] = _ts()
            _flush_notes()
            log.info("Note updated: %s", note_id)
            return n
    return None


def delete_note(note_id: str) -> bool:
    """Delete a note by ID. Returns True if found."""
    notes = _load_notes()
    before = len(notes)
    notes[:] = [n for n in notes if n["id"] != note_id]
    if len(notes) < before:
        _flush_notes()
        log.info("Note deleted: %s", note_id)
        return True
    return False


def pin_note(note_id: str, pinned: bool = True) -> dict | None:
    """Toggle pin on a note."""
    return update_note(note_id, pinned=pinned)


def list_notes(
    category: str = "",
    search: str = "",
    sort: str = "newest",
) -> list[dict]:
    """List notes with optional category filter, search, and sort."""
    notes = list(_load_notes())

    if category:
        notes = [n for n in notes if n.get("category") == category]
    if search:
        q = search.lower()
        notes = [n for n in notes if q in n.get("text", "").lower()
                 or q in " ".join(n.get("tags", [])).lower()]

    # Sort: pinned always first, then by sort key
    if sort == "oldest":
        notes.sort(key=lambda n: n.get("created", ""))
    else:  # newest
        notes.sort(key=lambda n: n.get("created", ""), reverse=True)

    # Pinned on top
    pinned = [n for n in notes if n.get("pinned")]
    unpinned = [n for n in notes if not n.get("pinned")]
    return pinned + unpinned


def get_note(note_id: str) -> dict | None:
    """Get a single note by ID."""
    for n in _load_notes():
        if n["id"] == note_id:
            return n
    return None


def get_note_categories() -> list[str]:
    """Return all unique categories."""
    cats = set()
    for n in _load_notes():
        cats.add(n.get("category", "general"))
    return sorted(cats)


def clear_notes() -> int:
    """Delete all notes. Returns count deleted."""
    notes = _load_notes()
    count = len(notes)
    notes.clear()
    _flush_notes()
    return count
