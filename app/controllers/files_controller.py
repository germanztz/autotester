"""Files controller: upload, rename, delete PDF projects."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, request, url_for

from app.utils.validators import safe_project_name

files_bp = Blueprint("files", __name__)


@files_bp.route("/upload", methods=["POST"])
def upload():
    """Handle a PDF upload and create a new project directory."""
    file = request.files.get("pdf")
    project_name = request.form.get("project_name", "").strip()

    if not file or not file.filename:
        flash("No file selected.", "danger")
        return redirect(url_for("main.index"))

    safe_name = safe_project_name(project_name or file.filename.rsplit(".", 1)[0])
    file_manager = current_app.extensions["file_manager"]

    try:
        entry = file_manager.save_upload(
            file.stream,
            original_filename=file.filename,
            project_name=safe_name,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    flash(f"Uploaded '{entry.name}' successfully.", "success")
    return redirect(url_for("main.index"))


@files_bp.route("/<project_name>/rename", methods=["POST"])
def rename(project_name: str):
    """Rename a project directory."""
    new_name = request.form.get("new_name", "").strip()
    if not new_name:
        flash("New name cannot be empty.", "danger")
        return redirect(url_for("main.index"))

    safe_new = safe_project_name(new_name)
    file_manager = current_app.extensions["file_manager"]

    try:
        final = file_manager.rename_project(project_name, safe_new)
    except (FileNotFoundError, ValueError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    flash(f"Renamed to '{final}'.", "success")
    return redirect(url_for("main.index"))


@files_bp.route("/<project_name>/delete", methods=["POST"])
def delete(project_name: str):
    """Delete a project directory."""
    file_manager = current_app.extensions["file_manager"]
    try:
        file_manager.delete_project(project_name)
    except (FileNotFoundError, ValueError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    flash(f"Deleted '{project_name}'.", "success")
    return redirect(url_for("main.index"))