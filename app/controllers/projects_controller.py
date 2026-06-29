"""Projects controller: view individual project pages."""
from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template

from app.utils.logging_setup import get_logger

projects_bp = Blueprint("projects", __name__)
logger = get_logger()


@projects_bp.route("/<project_name>")
def show(project_name: str):
    """Render the main page with the given project pre-selected."""
    file_manager = current_app.extensions["file_manager"]
    projects = file_manager.list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        abort(404)

    display_name = project.digest_title or project.name

    return render_template(
        "index.html",
        selected_project=project_name,
        selected_display_name=display_name,
    )
