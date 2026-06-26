"""Configuration controller: view and update app settings."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

config_bp = Blueprint("config", __name__)


@config_bp.route("/", methods=["GET"])
def show():
    """Render the configuration page."""
    return render_template("config.html")


@config_bp.route("/", methods=["POST"])
def update():
    """Persist submitted configuration values (theme, options)."""
    config_manager = current_app.extensions["config_manager"]

    payload: dict = {}
    theme = request.form.get("theme")
    if theme:
        payload["theme"] = theme

    try:
        config_manager.update(**payload)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("config.show"))

    flash("Configuration saved.", "success")
    return redirect(url_for("config.show"))