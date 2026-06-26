"""AI controller: status polling, project list, and config validation endpoints."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.utils.logging_setup import get_logger

ai_bp = Blueprint("ai", __name__)
logger = get_logger()


@ai_bp.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    """Return the current state of an async digest job."""
    runner = current_app.extensions["job_runner"]
    return jsonify(runner.get(job_id))


@ai_bp.route("/projects", methods=["GET"])
def projects():
    """Return the list of projects with their current digest state.

    Consumed by the sidebar poller; kept lightweight so 1 Hz polling is OK.
    Registered at ``/ai/projects`` because the AI blueprint already lives
    under the ``/ai`` URL prefix.
    """
    file_manager = current_app.extensions["file_manager"]
    entries = [e.to_dict() for e in file_manager.list_projects()]
    return jsonify({"projects": entries})


@ai_bp.route("/validate", methods=["POST"])
def validate():
    """Check if the configured Ollama URL is reachable.

    Accepts an optional JSON body ``{"url": "..."}`` to override the
    configured URL. Returns ``{"ok": bool, "message": str}``.
    """
    ai_manager = current_app.extensions["ai_manager"]
    payload = request.get_json(silent=True) or {}
    target = payload.get("url")
    ok, msg = ai_manager.validate_ollama(url=target)
    if ok:
        logger.info("Ollama reachable: %s", target or ai_manager.get_ia_settings()["ollama_url"])
    else:
        logger.warning("Ollama validation failed: %s", msg)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 503)