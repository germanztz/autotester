"""Configuration controller: view and update app settings."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

config_bp = Blueprint("config", __name__)


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@config_bp.route("/", methods=["GET"])
def show():
    """Render the configuration page."""
    ai_manager = current_app.extensions["ai_manager"]
    ollama_ok, ollama_msg = ai_manager.validate_ollama()
    return render_template(
        "config.html",
        ollama_ok=ollama_ok,
        ollama_msg=ollama_msg,
    )


@config_bp.route("/", methods=["POST"])
def update():
    """Persist submitted configuration values (theme + IA settings).

    When the IA form is filled, the new values are validated and the
    Ollama URL is probed: an unreachable Ollama is *advisory* — the
    config still saves, but a warning flash is shown.
    """
    config_manager = current_app.extensions["config_manager"]
    ai_manager = current_app.extensions["ai_manager"]

    theme = request.form.get("theme")
    if theme:
        try:
            config_manager.update(theme=theme)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("config.show"))

    # IA section
    ia_payload: dict = {}
    ollama_url = request.form.get("ollama_url", "").strip()
    if ollama_url:
        ia_payload["ollama_url"] = ollama_url
    embedding_model = request.form.get("embedding_model", "").strip()
    if embedding_model:
        ia_payload["embedding_model"] = embedding_model
    chunk_size = _parse_int(request.form.get("chunk_size"))
    if chunk_size is not None:
        ia_payload["chunk_size"] = chunk_size
    chunk_overlap = _parse_int(request.form.get("chunk_overlap"))
    if chunk_overlap is not None:
        ia_payload["chunk_overlap"] = chunk_overlap

    if ia_payload:
        try:
            config_manager.update_ia(**ia_payload)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("config.show"))

        # Advisory check
        ok, msg = ai_manager.validate_ollama()
        if ok:
            flash(f"IA settings saved. {msg}", "success")
        else:
            flash(f"IA settings saved, but: {msg}", "warning")
        return redirect(url_for("config.show"))

    flash("Configuration saved.", "success")
    return redirect(url_for("config.show"))