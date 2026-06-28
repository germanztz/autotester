"""Configuration controller: view and update app settings."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.utils.logging_setup import get_logger, setup_logging

config_bp = Blueprint("config", __name__)
logger = get_logger()


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
    segmenter = current_app.extensions["segmenter"]
    config_manager = current_app.extensions["config_manager"]
    ollama_ok, ollama_msg = segmenter.validate_ollama()
    return render_template(
        "config.html",
        ollama_ok=ollama_ok,
        ollama_msg=ollama_msg,
        log_level=config_manager.load().get("logging", {}).get("level", "INFO"),
    )


@config_bp.route("/", methods=["POST"])
def update():
    """Persist all submitted configuration values (theme + IA + logging).

    All sections are saved in a single pass. Validation errors for one
    section do not prevent valid sections from being saved. An Ollama
    reachability probe is performed after the IA section is saved.
    """
    config_manager = current_app.extensions["config_manager"]
    segmenter = current_app.extensions["segmenter"]
    errors: list[str] = []
    ia_updated = False
    log_level_updated = False

    # Theme
    theme = request.form.get("theme")
    if theme:
        try:
            config_manager.update(theme=theme)
        except ValueError as exc:
            logger.warning("Theme update failed: %s", exc)
            errors.append(str(exc))

    # IA section
    ia_payload: dict = {}
    ollama_url = request.form.get("ollama_url", "").strip()
    if ollama_url:
        ia_payload["ollama_url"] = ollama_url
    ollama_model = request.form.get("ollama_model", "").strip()
    if ollama_model:
        ia_payload["ollama_model"] = ollama_model
    chunk_size = _parse_int(request.form.get("chunk_size"))
    if chunk_size is not None:
        ia_payload["chunk_size"] = chunk_size
    chunk_overlap = _parse_int(request.form.get("chunk_overlap"))
    if chunk_overlap is not None:
        ia_payload["chunk_overlap"] = chunk_overlap

    # Prompts
    system_prompt = request.form.get("system_prompt")
    if system_prompt is not None:
        ia_payload["system_prompt"] = system_prompt
    user_prompt_tpl = request.form.get("user_prompt_tpl")
    if user_prompt_tpl is not None:
        ia_payload["user_prompt_tpl"] = user_prompt_tpl
    title_user_prompt_tpl = request.form.get("title_user_prompt_tpl")
    if title_user_prompt_tpl is not None:
        ia_payload["title_user_prompt_tpl"] = title_user_prompt_tpl

    if ia_payload:
        try:
            config_manager.update_ia(**ia_payload)
            ia_updated = True
        except ValueError as exc:
            logger.warning("IA update failed: %s", exc)
            errors.append(str(exc))

    # Logging section
    log_level = request.form.get("log_level", "").strip()
    if log_level:
        try:
            config_manager.update_logging(level=log_level)
            log_level_updated = True
            setup_logging(log_level)
        except ValueError as exc:
            logger.warning("Logging update failed: %s", exc)
            errors.append(str(exc))

    # Flush any validation errors.
    if errors:
        flash(errors[0], "danger")
        logger.info("Configuration saved by user (with errors)")
        return redirect(url_for("config.show"))

    logger.info("Configuration saved by user")

    # Success feedback.
    if ia_updated:
        ok, msg = segmenter.validate_ollama()
        if ok:
            logger.info(
                "Ollama reachable: %s",
                segmenter._get_ia_settings()["ollama_url"],
            )
            flash(f"Settings saved. {msg}", "success")
        else:
            logger.warning("Ollama unreachable: %s", msg)
            flash(f"Settings saved, but: {msg}", "warning")
    elif log_level_updated:
        flash(f"Settings saved. Log level set to {log_level}.", "success")
    else:
        flash("Settings saved.", "success")

    return redirect(url_for("config.show"))