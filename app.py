"""
app.py — Flask web app for the AI Agent.

Provides:
  • Tool gallery with thumbnail cards
  • Direct tool testing (pick a tool, enter input, see output)
  • Chat mode (LLM-powered ReAct loop or keyword fallback)
  • Memory viewer
  • LLM configuration & status API
"""

import time
import json as _json
from flask import Flask, render_template, request, jsonify, Response
from tools import TOOL_REGISTRY
from agent import AgentForge
from log_config import get_logger, ring_handler
import activity_store

log = get_logger("app")

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload
agent = AgentForge(name="WebAgent")
log.info("Flask app created, agent initialised")

# ── Tool metadata for the UI (icons, colors, example inputs) ─────────
TOOL_META = {
    "calculator": {
        "icon": "🧮", "color": "#6366f1",
        "example": "factorial(10) / sqrt(144)",
        "category": "Math",
    },
    "get_datetime": {
        "icon": "🕐", "color": "#0891b2",
        "example": "+5:30",
        "category": "Utility",
    },
    "weather_lookup": {
        "icon": "🌦️", "color": "#f59e0b",
        "example": "Tokyo",
        "category": "Web API",
    },
    "web_search": {
        "icon": "🔍", "color": "#10b981",
        "example": "Python programming tutorials",
        "category": "Web API",
    },
    "wikipedia_lookup": {
        "icon": "📚", "color": "#8b5cf6",
        "example": "Alan Turing",
        "category": "Web API",
    },
    "url_fetcher": {
        "icon": "🌐", "color": "#ec4899",
        "example": "https://httpbin.org/json",
        "category": "Web API",
    },
    "unit_converter": {
        "icon": "⚖️", "color": "#14b8a6",
        "example": "100 km to miles",
        "category": "Math",
    },
    "file_manager": {
        "icon": "📁", "color": "#f97316",
        "example": "list .",
        "category": "System",
    },
    "system_info": {
        "icon": "💻", "color": "#64748b",
        "example": "",
        "category": "System",
    },
    "text_analyzer": {
        "icon": "📝", "color": "#a855f7",
        "example": "The quick brown fox jumps over the lazy dog near the river bank",
        "category": "Text",
    },
    "hash_encode": {
        "icon": "🔐", "color": "#ef4444",
        "example": "sha256 hello world",
        "category": "Crypto",
    },
    "ip_lookup": {
        "icon": "🌍", "color": "#3b82f6",
        "example": "",
        "category": "Web API",
    },
    "note_taker": {
        "icon": "📌", "color": "#eab308",
        "example": "save Remember to review the agent code",
        "category": "Utility",
    },
    "document_ocr": {
        "icon": "📷", "color": "#0ea5e9",
        "example": "status",
        "category": "AI",
    },
}


@app.route("/")
def index():
    """Render the main page with tool cards."""
    log.info("GET / — serving index page")
    tools_info = []
    for name, info in TOOL_REGISTRY.items():
        meta = TOOL_META.get(name, {"icon": "\U0001f527", "color": "#64748b", "example": "", "category": "Other"})
        tools_info.append({
            "name": name,
            "description": info["description"],
            "icon": meta["icon"],
            "color": meta["color"],
            "example": meta["example"],
            "category": meta["category"],
        })
    log.debug("Loaded %d tools for index page", len(tools_info))
    return render_template("index.html", tools=tools_info)


@app.route("/api/tool", methods=["POST"])
def run_tool():
    """Run a single tool directly and return its output."""
    data = request.get_json()
    tool_name = data.get("tool", "")
    tool_input = data.get("input", "")
    log.info("POST /api/tool — tool=%s  input=%s", tool_name, tool_input[:120])

    if tool_name not in TOOL_REGISTRY:
        log.warning("Unknown tool requested: %s", tool_name)
        return jsonify({"error": f"Unknown tool: {tool_name}"}), 400

    try:
        t0 = time.perf_counter()
        result = TOOL_REGISTRY[tool_name]["function"](tool_input)
        elapsed = (time.perf_counter() - t0) * 1000
        log.info("Tool %s completed in %.1f ms  result_len=%d", tool_name, elapsed, len(result))
        log.debug("Tool %s result: %s", tool_name, result[:300])
        # Auto-log to activity journal
        activity_store.log_activity(
            act_type="tool", tool=tool_name,
            input_text=tool_input, output_text=result,
            success=True, duration_ms=elapsed,
        )
        return jsonify({"tool": tool_name, "input": tool_input, "result": result})
    except Exception as e:
        log.exception("Tool %s raised an exception", tool_name)
        activity_store.log_activity(
            act_type="tool", tool=tool_name,
            input_text=tool_input, output_text=str(e),
            success=False,
        )
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    """Run the full agent loop on a user message."""
    data = request.get_json()
    user_input = data.get("message", "").strip()
    log.info("POST /api/chat — message=%s", user_input[:200])

    if not user_input:
        log.warning("Empty chat message received")
        return jsonify({"error": "Empty message"}), 400

    try:
        t0 = time.perf_counter()
        # Agent now returns a dict with answer, steps, plan, mode, model
        result = agent.run(user_input)
        elapsed = (time.perf_counter() - t0) * 1000
        log.info("Chat completed in %.1f ms  mode=%s  steps=%d",
                 elapsed, result.get("mode"), len(result.get("steps", [])))
        log.debug("Chat answer: %s", result.get("answer", "")[:300])
        # Auto-log to activity journal
        tools_used = ", ".join(
            s.get("tool", "") for s in result.get("steps", [])
            if s.get("tool") and s["tool"] != "none"
        )
        activity_store.log_activity(
            act_type="chat", tool=tools_used,
            input_text=user_input, output_text=result.get("answer", ""),
            success=True, duration_ms=elapsed,
            mode=result.get("mode", ""), model=result.get("model", ""),
            steps=len(result.get("steps", [])),
        )
        return jsonify(result)
    except Exception as e:
        log.exception("Chat handler raised an exception")
        activity_store.log_activity(
            act_type="chat", input_text=user_input,
            output_text=str(e), success=False,
        )
        return jsonify({"error": str(e)}), 500


@app.route("/api/memory")
def memory():
    """Return the agent's memory."""
    log.info("GET /api/memory — %d entries", len(agent.memory))
    return jsonify({"memory": agent.memory, "count": len(agent.memory)})


@app.route("/api/memory/clear", methods=["POST"])
def clear_memory():
    """Clear the agent's memory."""
    log.info("POST /api/memory/clear — clearing %d entries", len(agent.memory))
    agent.memory.clear()
    return jsonify({"status": "ok", "message": "Memory cleared"})


@app.route("/api/tools")
def list_tools():
    """Return tool metadata as JSON."""
    tools = {}
    for name, info in TOOL_REGISTRY.items():
        meta = TOOL_META.get(name, {})
        tools[name] = {
            "description": info["description"],
            "icon": meta.get("icon", "🔧"),
            "example": meta.get("example", ""),
            "category": meta.get("category", "Other"),
        }
    return jsonify(tools)


# ── LLM Configuration API ────────────────────────────────────────────

@app.route("/api/llm/status")
def llm_status():
    """Check LLM provider status and availability."""
    log.info("GET /api/llm/status")
    available, message = agent.llm.is_available()
    log.info("LLM status: available=%s  message=%s", available, message)
    return jsonify({
        "available": available,
        "message": message,
        "config": agent.llm_config.to_dict(),
    })


@app.route("/api/llm/models")
def llm_models():
    """List available models from the current provider."""
    log.info("GET /api/llm/models")
    models = agent.llm.list_models()
    log.info("Available models: %s  current=%s", models, agent.llm_config.model)
    return jsonify({"models": models, "current": agent.llm_config.model})


@app.route("/api/llm/config", methods=["GET", "POST"])
def llm_config():
    """Get or update LLM configuration."""
    if request.method == "GET":
        log.info("GET /api/llm/config")
        return jsonify(agent.llm_config.to_dict())

    data = request.get_json()
    log.info("POST /api/llm/config — updating: %s", data)
    agent.llm_config.update(data)
    # Recreate provider with updated config
    agent.llm = LLMProvider(agent.llm_config)
    log.info("LLM config updated: %s", agent.llm_config.to_dict())
    return jsonify({"status": "ok", "config": agent.llm_config.to_dict()})


# Need to import LLMProvider for the config endpoint
from llm_provider import LLMProvider


# ── Activity & Notes API ──────────────────────────────────────────────

@app.route("/api/activity")
def api_activity():
    """List activities with filters: ?type=tool&tool=weather&days=7&page=1&limit=50"""
    result = activity_store.get_activities(
        act_type=request.args.get("type", ""),
        tool=request.args.get("tool", ""),
        days=request.args.get("days", 0, type=int),
        page=request.args.get("page", 1, type=int),
        limit=request.args.get("limit", 50, type=int),
    )
    return jsonify(result)


@app.route("/api/activity/stats")
def api_activity_stats():
    """Usage statistics."""
    days = request.args.get("days", 30, type=int)
    return jsonify(activity_store.get_activity_stats(days))


@app.route("/api/activity/export")
def api_activity_export():
    """Export activities as JSON or CSV."""
    fmt = request.args.get("format", "json")
    data = activity_store.export_activities(fmt)
    mime = "text/csv" if fmt == "csv" else "application/json"
    return Response(data, mimetype=mime,
                    headers={"Content-Disposition": f"attachment; filename=activity.{fmt}"})


@app.route("/api/notes", methods=["GET"])
def api_notes_list():
    """List notes with optional category filter, search, sort."""
    notes = activity_store.list_notes(
        category=request.args.get("category", ""),
        search=request.args.get("search", ""),
        sort=request.args.get("sort", "newest"),
    )
    categories = activity_store.get_note_categories()
    return jsonify({"notes": notes, "categories": categories, "total": len(notes)})


@app.route("/api/notes", methods=["POST"])
def api_notes_create():
    """Create a new note."""
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Note text is required"}), 400
    note = activity_store.save_note(
        text=text,
        category=data.get("category", "general"),
        tags=data.get("tags", []),
        color=data.get("color", "default"),
        source=data.get("source", "manual"),
    )
    return jsonify({"status": "ok", "note": note})


@app.route("/api/notes/<note_id>", methods=["PUT"])
def api_notes_update(note_id):
    """Update a note."""
    data = request.get_json()
    note = activity_store.update_note(note_id, **data)
    if note is None:
        return jsonify({"error": "Note not found"}), 404
    return jsonify({"status": "ok", "note": note})


@app.route("/api/notes/<note_id>", methods=["DELETE"])
def api_notes_delete(note_id):
    """Delete a note."""
    if activity_store.delete_note(note_id):
        return jsonify({"status": "ok"})
    return jsonify({"error": "Note not found"}), 404


@app.route("/api/notes/<note_id>/pin", methods=["POST"])
def api_notes_pin(note_id):
    """Toggle pin on a note."""
    data = request.get_json() or {}
    pinned = data.get("pinned", True)
    note = activity_store.pin_note(note_id, pinned)
    if note is None:
        return jsonify({"error": "Note not found"}), 404
    return jsonify({"status": "ok", "note": note})


# ── OCR File Upload ───────────────────────────────────────────────────

import os as _os
from pathlib import Path as _Path

_OCR_UPLOADS_DIR = _Path(__file__).parent / "ocr_uploads"


@app.route("/api/ocr/upload", methods=["POST"])
def ocr_upload():
    """Handle image upload for OCR scanning."""
    log.info("POST /api/ocr/upload")
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "No file selected"}), 400

        allowed_ext = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
        ext = _os.path.splitext(f.filename)[1].lower()
        if ext not in allowed_ext:
            return jsonify({"error": f"Unsupported format '{ext}'. Use: {', '.join(sorted(allowed_ext))}"}), 400

        _OCR_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        import time as _time
        safe_name = f"{int(_time.time())}_{f.filename.replace(' ', '_')}"
        save_path = _OCR_UPLOADS_DIR / safe_name
        f.save(str(save_path))
        file_size = save_path.stat().st_size
        log.info("Uploaded file saved to %s (%d bytes)", save_path, file_size)

        # Run OCR via the tool
        t0 = time.perf_counter()
        result = TOOL_REGISTRY["document_ocr"]["function"](f"scan {save_path}")
        elapsed = (time.perf_counter() - t0) * 1000
        log.info("OCR upload completed in %.1f ms", elapsed)
        activity_store.log_activity(
            act_type="tool", tool="document_ocr",
            input_text=f"scan {save_path}", output_text=result,
            success=True, duration_ms=elapsed,
        )
        return jsonify({"tool": "document_ocr", "input": f.filename, "result": result})
    except Exception as e:
        log.exception("OCR upload processing failed")
        return jsonify({"error": str(e)}), 500


# ── Live Log Streaming (SSE) ─────────────────────────────────────────

@app.route("/api/logs/stream")
def log_stream():
    """Server-Sent Events endpoint for live log streaming to the UI."""
    log.info("SSE /api/logs/stream — client connected")

    def generate():
        last_seq = -1
        while True:
            entries = ring_handler.get_since(last_seq)
            for entry in entries:
                last_seq = entry["seq"]
                data = _json.dumps(entry)
                yield f"data: {data}\n\n"
            time.sleep(0.4)  # poll interval

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/logs/recent")
def log_recent():
    """Return the last N log entries as JSON (for initial load)."""
    n = request.args.get("n", 100, type=int)
    entries = ring_handler.get_since(-1)
    return jsonify(entries[-n:])


if __name__ == "__main__":
    log.info("Agent Web App starting on http://localhost:5000")
    app.run(debug=True, port=5000)
