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
        "Uploaded PDF: project=%s file=%s size_bytes=%s",
        entry.name,
        file.filename,
        entry.size_bytes,
    )

    # Enqueue async lazy digest of the just-saved PDF. The job runner owns
# the markdown extraction and page-by-page embedding on a background
# thread; we only register the project with the runner here.
    ai_manager = current_app.extensions["ai_manager"]
    lazy_ai_manager = current_app.extensions["lazy_ai_manager"]
    job_runner = current_app.extensions["job_runner"]
    pdfs = sorted(file_manager.project_path(entry.name).glob("*.pdf"))
    if not pdfs:
        logger.error("PDF not found on disk after upload for project=%s", entry.name)
        if wants_json:
            return jsonify({"error": "PDF not found after upload."}), 500
        flash("PDF not found after upload.", "danger")
        return redirect(url_for("main.index"))
    pdf_path = pdfs[0]
    job_id = lazy_ai_manager.start(entry.name, job_runner)
    logger.info(
        "AI digest queued: project=%s job_id=%s", entry.name, job_id
    )

    if wants_json:
        return jsonify({"job_id": job_id, "project": entry.name}), 202

    flash(f"Uploaded '{entry.name}'. Indexing...", "info")
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
        logger.warning("Rename failed: %s -> %s: %s", project_name, safe_new, exc)
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    logger.info("Renamed project: %s -> %s", project_name, final)
    flash(f"Renamed to '{final}'.", "success")
    return redirect(url_for("main.index"))


@files_bp.route("/<project_name>/delete", methods=["POST"])
def delete(project_name: str):
    """Delete a project directory."""
    file_manager = current_app.extensions["file_manager"]
    try:
        file_manager.delete_project(project_name)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("Delete failed: %s: %s", project_name, exc)
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    logger.info("Deleted project: %s", project_name)
    flash(f"Deleted '{project_name}'.", "success")
    return redirect(url_for("main.index"))


@files_bp.route("/<project_name>/cancel", methods=["POST"])
def cancel_digest(project_name: str):
    """Stop the running digest for the given project.

    Cooperative cancellation: the running worker checks the cancel flag
    between pages and exits cleanly. Remaining ``### Page N`` markers
    are left in place so the digest can resume later.
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
    logger.info("Digest cancel requested: project=%s", project_name)

    if "application/json" in (request.headers.get("Accept") or ""):
        return jsonify({"ok": True, "project": project_name})

    flash(f"Stopping digest for '{project_name}'...", "info")
    return redirect(url_for("main.index"))