"""Flask application factory for autotester.

Wires together configuration, blueprints, models and static assets.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from app.config import Config
from app.models.config_manager import ConfigManager
from app.models.file_manager import FileManager


def create_app(config_object: type[Config] | None = None) -> Flask:
    """Create and configure a Flask application instance.

    Args:
        config_object: Optional configuration class overriding the default.

    Returns:
        Configured Flask app ready to serve requests.
    """
    app = Flask(
        __name__,
        static_folder="views/static",
        template_folder="views/templates",
    )
    app.config.from_object(config_object or Config)

    base_dir = Path(app.config["BASE_DIR"]).resolve()
    projects_dir = Path(app.config["PROJECTS_DIR"]).resolve()
    config_path = Path(app.config["CONFIG_PATH"]).resolve()
    projects_dir.mkdir(parents=True, exist_ok=True)

    config_manager = ConfigManager(config_path)
    file_manager = FileManager(projects_dir)

    app.extensions["config_manager"] = config_manager
    app.extensions["file_manager"] = file_manager

    @app.context_processor
    def inject_globals() -> dict:
        """Make managers and theme available to all templates."""
        cfg = config_manager.load()
        return {
            "app_config": cfg,
            "current_theme": cfg.get("theme", "system"),
            "projects": file_manager.list_projects(),
        }

    from app.controllers.main_controller import main_bp
    from app.controllers.files_controller import files_bp
    from app.controllers.config_controller import config_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(files_bp, url_prefix="/files")
    app.register_blueprint(config_bp, url_prefix="/config")

    return app