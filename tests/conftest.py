"""pytest configuration and shared fixtures for autotester tests."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from app import create_app
from app.config import Config
from app.utils.logging_setup import LOGGER_NAME, reset_logger


class TestConfig(Config):
    """Test-time configuration overriding paths to use temporary dirs."""

    TESTING = True
    DEBUG = False


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Iterator[dict]:
    """Create an isolated workspace with config.yaml and projects/ dirs."""
    projects_dir = tmp_path / "projects"
    config_path = tmp_path / "config.yaml"
    projects_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump({"theme": "system", "app_name": "autotester"}))

    yield {
        "root": tmp_path,
        "projects": projects_dir,
        "config": config_path,
    }

    if tmp_path.exists():
        shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture(autouse=True)
def _quiet_logger():
    """Reset the autotester logger after each test.

    Does NOT touch the level before the test runs, so that the
    ``caplog`` fixture (which may set the level on the autotester
    logger) keeps working as expected. The teardown clears any
    handlers the application code attached during the test to prevent
    accumulation across tests.
    """
    yield
    reset_logger()


@pytest.fixture(autouse=True)
def _shutdown_job_runner(app):
    """Shut down the per-test JobRunner executor to avoid leaking threads.

    Without this, a long-running digest submitted by an upload test can
    outlive the test function and try to schedule work on an executor
    that has been garbage-collected, producing spurious
    ``RuntimeError: cannot schedule new futures after interpreter shutdown``
    errors.

    Tests use a FakeOllama so the in-flight digest completes almost
    instantly; ``wait=True`` is safe.
    """
    yield
    runner = app.extensions.get("job_runner")
    if runner is not None:
        runner.shutdown(wait=True)


@pytest.fixture
def app(temp_workspace: dict) -> Iterator:
    """Create a Flask app configured for the temp workspace."""
    class _Cfg(TestConfig):
        BASE_DIR = str(temp_workspace["root"])
        PROJECTS_DIR = str(temp_workspace["projects"])
        CONFIG_PATH = str(temp_workspace["config"])
        SECRET_KEY = "test-secret"

    flask_app = create_app(_Cfg)
    flask_app.config.update(TESTING=True)
    yield flask_app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid PDF binary payload."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000111 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n178\n%%EOF\n"
    )