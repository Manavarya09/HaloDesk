#!/usr/bin/env python3
"""Web API server for HaloDesk."""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime
from threading import Lock

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

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

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="frontend", static_url_path="")
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_agent: AgentLoop | None = None
_lock = Lock()


def get_agent() -> AgentLoop:
    global _agent
    if _agent is None:
        cfg = load_config()
        db = SQLiteStore(cfg["memory"]["sqlite_path"])
        faiss = FAISSRetriever(cfg["memory"])
        registry = ToolRegistry()

        registry.register(LinkupSearchTool(cfg.get("linkup", {})))
        email_cfg = cfg.get("email", {})
        registry.register(ListEmailsTool(email_cfg))
        registry.register(ReadEmailTool(email_cfg))
        registry.register(DraftReplyTool())
        doc_cfg = cfg.get("documents", {})
        registry.register(ReadDocumentTool())
        registry.register(ListDocumentsTool(doc_cfg))
        registry.register(SummarizeDocumentTool())
        cal_cfg = cfg.get("calendar", {})
        registry.register(ListEventsTool(cal_cfg))
        registry.register(CreateEventTool(cal_cfg))
        registry.register(CreateReminderTool(cal_cfg))
        registry.register(MemoryStoreTool(db, faiss))
        registry.register(MemoryRecallTool(db, faiss))

        _agent = AgentLoop(cfg, registry, db, faiss)
        logger.info("Agent initialized — session %s", _agent.session_id)
    return _agent


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """Send a message (with optional file attachments) to the agent."""
    # Support both JSON and multipart/form-data
    if request.content_type and "multipart" in request.content_type:
        message = request.form.get("message", "").strip()
        privacy = request.form.get("privacy", "true").lower() != "false"
        uploaded_files = request.files.getlist("files")

        attachment_paths = []
        for f in uploaded_files:
            if f.filename:
                safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{f.filename}"
                save_path = UPLOAD_DIR / safe_name
                f.save(str(save_path))
                attachment_paths.append(str(save_path))
                logger.info("File uploaded: %s", save_path)
    else:
        data = request.get_json(force=True)
        message = data.get("message", "").strip()
        privacy = data.get("privacy", True)
        attachment_paths = []

    if not message:
        return jsonify({"error": "Empty message"}), 400

    agent = get_agent()
    agent.privacy_enabled = privacy

    with _lock:
        try:
            response = agent.run(message, attachments=attachment_paths or None)

            return jsonify({
                "response": response,
                "session_id": agent.session_id,
                "timestamp": datetime.now().isoformat(),
                "privacy_active": privacy,
                "ai_view": agent.last_redacted_input,
                "generated_files": agent.last_generated_files,
                "attachments": [Path(p).name for p in attachment_paths],
            })
        except Exception as exc:
            logger.error("Agent error: %s", traceback.format_exc())
            return jsonify({"error": str(exc)}), 500


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Upload files for context. Returns saved paths."""
    files = request.files.getlist("files")
    saved = []
    for f in files:
        if f.filename:
            safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{f.filename}"
            save_path = UPLOAD_DIR / safe_name
            f.save(str(save_path))
            saved.append({"name": f.filename, "path": str(save_path), "size_kb": round(save_path.stat().st_size / 1024, 1)})
    return jsonify({"files": saved})


@app.route("/api/download")
def download_file():
    """Download a generated file (.ics, .eml, etc.)."""
    filepath = request.args.get("path", "")
    p = Path(filepath)
    if not p.exists():
        return jsonify({"error": "File not found"}), 404
    # Security: only allow files from data/ directory
    try:
        p.resolve().relative_to(Path("data").resolve())
    except ValueError:
        return jsonify({"error": "Access denied"}), 403
    return send_file(str(p.resolve()), as_attachment=True, download_name=p.name)


@app.route("/api/download/ics")
def download_ics():
    """Legacy endpoint — redirects to generic download."""
    return download_file()


@app.route("/api/download/eml")
def download_eml():
    """Legacy endpoint — redirects to generic download."""
    return download_file()


@app.route("/api/privacy", methods=["POST"])
def toggle_privacy():
    """Toggle privacy mode on/off."""
    data = request.get_json(force=True)
    enabled = data.get("enabled", True)
    agent = get_agent()
    agent.privacy_enabled = bool(enabled)
    return jsonify({"privacy_enabled": agent.privacy_enabled})


@app.route("/api/privacy", methods=["GET"])
def get_privacy():
    """Get current privacy status."""
    agent = get_agent()
    # Check which engine is available
    from tools.privacy import _load_presidio
    _, _, nlp_ok = _load_presidio()
    return jsonify({
        "privacy_enabled": agent.privacy_enabled,
        "engine": "presidio" if nlp_ok else "regex",
    })


@app.route("/api/tools", methods=["GET"])
def list_tools():
    agent = get_agent()
    tools = []
    for t in agent._registry.all_tools():
        tools.append({
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        })
    return jsonify({"tools": tools})


@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    agent = get_agent()
    tasks = agent._db.recent_tasks(agent.session_id, limit=20)
    return jsonify({"tasks": tasks})


@app.route("/api/memory", methods=["GET"])
def search_memory():
    query = request.args.get("q", "recent")
    agent = get_agent()
    results = agent._faiss.search(query, top_k=10)
    return jsonify({"memories": results})


@app.route("/api/session", methods=["GET"])
def session_info():
    agent = get_agent()
    return jsonify({
        "session_id": agent.session_id,
        "tools_count": len(agent._registry.names()),
        "tools": agent._registry.names(),
        "memory_size": agent._faiss.size,
        "privacy_enabled": agent.privacy_enabled,
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    """Comprehensive health check — verifies all prerequisites."""
    checks = {}
    all_ok = True

    # 1. Python version
    import platform
    checks["python"] = {
        "status": "ok",
        "version": platform.python_version(),
        "message": f"Python {platform.python_version()}"
    }

    # 2. Ollama reachable
    try:
        import requests as req
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        resp = req.get(f"{ollama_host}/api/tags", timeout=3)
        if resp.ok:
            models = [m["name"] for m in resp.json().get("models", [])]
            cfg = load_config()
            target_model = cfg["agent"]["model"]
            has_model = any(target_model in m for m in models)
            checks["ollama"] = {
                "status": "ok" if has_model else "warning",
                "message": f"Running, {'model found: ' + target_model if has_model else 'model ' + target_model + ' not found — run: ollama pull ' + target_model}",
                "models": models[:10],
                "target_model": target_model,
            }
            if not has_model:
                all_ok = False
        else:
            checks["ollama"] = {"status": "error", "message": "Ollama responded but returned an error"}
            all_ok = False
    except Exception as e:
        checks["ollama"] = {
            "status": "error",
            "message": "Cannot reach Ollama. Make sure it's running: ollama serve"
        }
        all_ok = False

    # 3. Linkup API key
    linkup_key = os.environ.get("LINKUP_API_KEY", "")
    if linkup_key and len(linkup_key) > 5:
        checks["linkup_api_key"] = {
            "status": "ok",
            "message": f"Set (ends with ...{linkup_key[-4:]})"
        }
    else:
        checks["linkup_api_key"] = {
            "status": "error",
            "message": "Not set. Run: set LINKUP_API_KEY=your-key (get one free at linkup.so)"
        }
        all_ok = False

    # 4. Key Python packages
    packages = {
        "flask": "flask",
        "ollama_sdk": "ollama",
        "faiss": "faiss",
        "sentence_transformers": "sentence_transformers",
        "fitz_pymupdf": "fitz",
    }
    pkg_results = {}
    for name, module in packages.items():
        try:
            __import__(module)
            pkg_results[name] = "ok"
        except ImportError:
            pkg_results[name] = "missing"
            if name in ("flask", "ollama_sdk"):
                all_ok = False

    checks["packages"] = {
        "status": "ok" if all(v == "ok" for v in pkg_results.values()) else "warning",
        "message": f"{sum(v == 'ok' for v in pkg_results.values())}/{len(pkg_results)} installed",
        "details": pkg_results,
    }

    # 5. Privacy engine
    try:
        from tools.privacy import _load_presidio
        _, _, nlp_ok = _load_presidio()
        checks["privacy_engine"] = {
            "status": "ok",
            "message": "Presidio NLP" if nlp_ok else "Regex fallback (install presidio for better detection)"
        }
    except Exception:
        checks["privacy_engine"] = {"status": "ok", "message": "Regex fallback"}

    # 6. Demo data
    demo_emails = Path("data/emails").exists()
    demo_cal = Path("data/calendars").exists()
    checks["demo_data"] = {
        "status": "ok" if (demo_emails or demo_cal) else "warning",
        "message": f"Emails: {'ready' if demo_emails else 'will seed on first use'}, Calendar: {'ready' if demo_cal else 'will seed on first use'}"
    }

    return jsonify({
        "healthy": all_ok,
        "checks": checks,
        "message": "All systems operational" if all_ok else "Some checks failed — see details above"
    })


if __name__ == "__main__":
    Path("frontend").mkdir(exist_ok=True)
    print("\nHaloDesk API running at http://localhost:5000\n")
    print("Health check: http://localhost:5000/api/health\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
