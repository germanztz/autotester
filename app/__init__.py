"""Flask application factory for autotester.

Wires together configuration, blueprints, models and static assets.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask

from app.config import Config
from app.models.config_manager import ConfigManager
from app.models.file_manager import FileManager
from app.models.game_state import GameManager
from app.models.semantic_segmenter import SemanticSegmenter
from app.services.digest_engine import LazyAIManager
from app.services.digest_supervisor import DigestSupervisor
from app.services.job_runner import JobRunner
from app.services.question_generator import QuestionGenerator
from app.services.question_engine import QuestionEngine
from app.utils.logging_setup import get_logger, setup_logging


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

    # Configure logging as early as possible so that any later log
    # statement during app construction is captured.
    log_level = (
        os.environ.get("AUTOTESTER_LOG_LEVEL")
        or config_manager.load().get("logging", {}).get("level", "INFO")
    )
    setup_logging(log_level)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.extensions["logger"] = get_logger()
    get_logger().info(
        "autotester starting (log level: %s, projects: %s, config: %s)",
        log_level,
        projects_dir,
        config_path,
    )
    file_manager = FileManager(projects_dir)
    segmenter = SemanticSegmenter(
        config_manager=config_manager,
        file_manager=file_manager,
        request_timeout=float(app.config.get("OLLAMA_PER_REQUEST_TIMEOUT", 60.0)),
        max_attempts=int(app.config.get("OLLAMA_MAX_ATTEMPTS", 3)),
        backoff_base=float(app.config.get("OLLAMA_BACKOFF_BASE_SECONDS", 1.0)),
    )
    game_manager = GameManager(file_manager=file_manager, config_manager=config_manager)

    lazy_ai_manager = LazyAIManager(
        segmenter=segmenter,
        file_manager=file_manager,
        game_manager=game_manager,
    )
    job_runner = JobRunner(
        max_workers=int(app.config.get("JOB_MAX_WORKERS", 2)),
        ttl_seconds=float(app.config.get("JOB_TTL_SECONDS", 60.0)),
    )
    question_generator = QuestionGenerator(
        llm_client=segmenter.llm,
        config_manager=config_manager,
    )
    question_engine = QuestionEngine(
        file_manager=file_manager,
        config_manager=config_manager,
        question_generator=question_generator,
        game_manager=game_manager,
    )

    app.extensions["config_manager"] = config_manager
    app.extensions["file_manager"] = file_manager
    app.extensions["segmenter"] = segmenter
    app.extensions["lazy_ai_manager"] = lazy_ai_manager
    app.extensions["job_runner"] = job_runner
    app.extensions["game_manager"] = game_manager
    app.extensions["question_generator"] = question_generator
    app.extensions["question_engine"] = question_engine

    digest_supervisor = DigestSupervisor(
        lazy_ai_manager=lazy_ai_manager,
        file_manager=file_manager,
        interval_seconds=float(
            app.config.get("DIGEST_POLL_INTERVAL_SECONDS", 60.0)
        ),
        long_interval_seconds=float(
            app.config.get("DIGEST_POLL_LONG_INTERVAL_SECONDS", 600.0)
        ),
        max_consecutive_failures=int(
            app.config.get("MAX_CONSECUTIVE_FAILURES", 5)
        ),
    )
    app.extensions["digest_supervisor"] = digest_supervisor
    digest_supervisor.start()

    # Log initial scan of projects directory.
    get_logger().info("Scanning ./projects/ for unprocessed projects...")
    pending = [e for e in file_manager.list_projects() if lazy_ai_manager.needs_digest(e.name)]
    get_logger().info("Projects pending processing: %d", len(pending))

    # Backfill questions for projects whose digest completed before the
    # question-generation feature existed, or after a partial crash.
    for entry in file_manager.list_projects():
        if entry.digest_state in ("complete", "processing") or lazy_ai_manager.needs_digest(entry.name):
            count = lazy_ai_manager.ensure_questions_generated(entry.name)
            if count:
                get_logger().info(
                    "Backfilled %d question(s) for %s",
                    count, entry.name,
                )

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
    from app.controllers.ai_controller import ai_bp
    from app.controllers.game_controller import game_bp
    from app.controllers.projects_controller import projects_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(files_bp, url_prefix="/files")
    app.register_blueprint(config_bp, url_prefix="/config")
    app.register_blueprint(ai_bp, url_prefix="/ai")
    app.register_blueprint(game_bp)
    app.register_blueprint(projects_bp, url_prefix="/projects")

    return app