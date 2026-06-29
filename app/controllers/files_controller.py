"""Files controller: upload, rename, delete, cancel PDF projects."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for

from app.utils.logging_setup import get_logger
from app.utils.validators import safe_project_name

files_bp = Blueprint("files", __name__)
logger = get_logger()


@files_bp.route("/upload", methods=["POST"])
def upload():
    """Handle a PDF upload, then enqueue an async AI digest job.

    Returns:
        - JSON ``{"job_id": str, "project": str}`` with HTTP 202 when the
          client sent ``Accept: application/json`` (used by the modal JS).
        - Standard redirect to ``/`` for classic browser form submits.
    """
    file = request.files.get("pdf")
    project_name = request.form.get("project_name", "").strip()
    wants_json = "application/json" in (request.headers.get("Accept") or "")

    if not file or not file.filename:
        logger.info("Upload rejected: no file selected")
        if wants_json:
            return jsonify({"error": "No file selected."}), 400
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
        logger.warning("Upload rejected for %r: %s", file.filename, exc)
        if wants_json:
            return jsonify({"error": str(exc)}), 400
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    logger.info(
        "User uploaded PDF | Project: %s | File: %s",
        entry.name,
        file.filename,
    )

    # The new PDF is on disk. The digest supervisor (started by the app
    # factory) will pick it up on its next iteration; we just kick the
    # supervisor so it doesn't have to wait the full poll interval before
    # the first page is embedded.
    supervisor = current_app.extensions.get("digest_supervisor")
    if supervisor is not None:
        supervisor.ensure_running()

    if wants_json:
        return jsonify({"project": entry.name, "status": "queued"}), 202

    return redirect(url_for("main.index"))


@files_bp.route("/<project_name>/rename", methods=["POST"])
def rename(project_name: str):
    """Rename a project directory and update title/language metadata."""
    title = (request.form.get("title") or request.form.get("new_name") or "").strip()
    language = (request.form.get("language") or "").strip()
    if not title:
        flash("Title cannot be empty.", "danger")
        return redirect(url_for("main.index"))

    file_manager = current_app.extensions["file_manager"]
    safe_new = safe_project_name(title)

    try:
        final = file_manager.rename_project(project_name, safe_new)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("Rename failed: %s -> %s: %s", project_name, safe_new, exc)
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    lazy_ai = current_app.extensions.get("lazy_ai_manager")
    if lazy_ai:
        lazy_ai._persist_state(final, title=title, language=language)

    logger.info(
        "Project renamed | %s -> %s | title=%s language=%s",
        project_name, final, title, language,
    )
    flash(f"Renamed to '{final}'.", "success")
    return redirect(url_for("main.index"))


@files_bp.route("/<project_name>/delete", methods=["POST"])
def delete(project_name: str):
    """Delete a project directory, cancelling any background jobs first."""
    # Cancel any in-flight job or running digest before removing files.
    job_runner = current_app.extensions.get("job_runner")
    lazy_ai = current_app.extensions.get("lazy_ai_manager")
    if job_runner:
        job_id = job_runner.find_by_project(project_name)
        if job_id:
            job_runner.cancel(job_id)
    if lazy_ai:
        lazy_ai.cancel(project_name)

    file_manager = current_app.extensions["file_manager"]
    try:
        file_manager.delete_project(project_name)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("Delete failed: %s: %s", project_name, exc)
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    logger.info("Project deleted | %s", project_name)
    flash(f"Deleted '{project_name}'.", "success")
    return redirect(url_for("main.index"))


@files_bp.route("/<project_name>/cancel", methods=["POST"])
def cancel_digest(project_name: str):
    """Stop the running digest for the given project.

    Cooperative cancellation: the running worker checks the cancel flag
    between pages and exits cleanly. Remaining ``### Page N`` markers
    are left in place and the project state is reset to ``queued`` so
    the supervisor will pick it up on the next scan and resume.
    """
    job_runner = current_app.extensions["job_runner"]
    lazy_ai = current_app.extensions["lazy_ai_manager"]

    # Try to cancel via the job registry first (in-flight job).
    job_id = job_runner.find_by_project(project_name)
    if job_id:
        job_runner.cancel(job_id)
    # Also set the LazyAIManager's own cancel flag — covers cases where
    # the work hasn't started yet but is queued, or where cancel is
    # requested via a path that doesn't go through the job registry.
    lazy_ai.cancel(project_name)
    # Reset digest state to queued so the supervisor will resume.
    lazy_ai.mark_unfailed(project_name)
    logger.info("Digest cancel requested: project=%s", project_name)

    if "application/json" in (request.headers.get("Accept") or ""):
        return jsonify({"ok": True, "project": project_name})

    return redirect(url_for("main.index"))