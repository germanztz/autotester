"""Application configuration for autotester."""
from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE_DIR / "projects"
CONFIG_PATH = BASE_DIR / "config.yaml"


class Config:
    """Default configuration class used by the Flask app factory."""

    SECRET_KEY = os.environ.get("AUTOTESTER_SECRET_KEY", "dev-secret-change-me")
    BASE_DIR = str(BASE_DIR)
    PROJECTS_DIR = str(PROJECTS_DIR)
    CONFIG_PATH = str(CONFIG_PATH)
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB upload limit
    ALLOWED_EXTENSIONS = {".pdf"}
    TESTING = False
    DEBUG = False