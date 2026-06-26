"""AI controller: status polling and config validation endpoints."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

ai_bp = Blueprint("ai", __name__)


@ai_bp.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    """Return the current state of an async digest job."""
    runner = current_app.extensions["job_runner"]
    return jsonify(runner.get(job_id))


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
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 503)