"""Tests for the autotester logger integration.

Verifies that key application events emit log records at the expected
level. Uses pytest's ``caplog`` fixture so we don't depend on stderr
output or the configured handler.
"""
from __future__ import annotations

import io
import logging
import time
from unittest.mock import patch

import pytest

from app.utils.logging_setup import LOGGER_NAME, setup_logging


@pytest.fixture
def autotester_caplog(caplog):
    """Attach caplog to the autotester logger at the requested level."""
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    return caplog


class TestFilesControllerLogging:
    def test_upload_logs_info_with_project_and_size(
        self, client, sample_pdf_bytes, autotester_caplog
    ):
        from test_ai_manager import FakeOllama

        client.application.extensions["ai_manager"].ollama = FakeOllama()
        client.post(
            "/files/upload",
            data={
                "project_name": "log_demo",
                "pdf": (io.BytesIO(sample_pdf_bytes), "doc.pdf"),
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        messages = [r.message for r in autotester_caplog.records]
        assert any("Uploaded PDF" in m and "log_demo" in m for m in messages)
        assert any("AI digest queued" in m and "log_demo" in m for m in messages)

    def test_rename_logs_info(self, client, sample_pdf_bytes, autotester_caplog):
        from test_ai_manager import FakeOllama

        client.application.extensions["ai_manager"].ollama = FakeOllama()
        client.post(
            "/files/upload",
            data={
                "project_name": "renamed",
                "pdf": (io.BytesIO(sample_pdf_bytes), "f.pdf"),
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        client.post("/files/renamed/rename", data={"new_name": "renamed2"})
        messages = [r.message for r in autotester_caplog.records]
        assert any("Renamed project" in m and "renamed2" in m for m in messages)

    def test_delete_logs_info(self, client, sample_pdf_bytes, autotester_caplog):
        from test_ai_manager import FakeOllama

        client.application.extensions["ai_manager"].ollama = FakeOllama()
        client.post(
            "/files/upload",
            data={
                "project_name": "doomed",
                "pdf": (io.BytesIO(sample_pdf_bytes), "f.pdf"),
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        client.post("/files/doomed/delete")
        messages = [r.message for r in autotester_caplog.records]
        assert any("Deleted project" in m and "doomed" in m for m in messages)


class TestConfigControllerLogging:
    def test_theme_change_logs_info(self, client, autotester_caplog):
        client.post("/config/", data={"theme": "dark"})
        messages = [r.message for r in autotester_caplog.records]
        assert any("Theme updated" in m and "dark" in m for m in messages)

    def test_log_level_change_logs_info(self, client, autotester_caplog):
        client.post("/config/", data={"log_level": "DEBUG"})
        messages = [r.message for r in autotester_caplog.records]
        assert any("Log level changed" in m and "DEBUG" in m for m in messages)
        # After saving DEBUG, the autotester logger should be at DEBUG.
        assert logging.getLogger(LOGGER_NAME).level == logging.DEBUG


class TestAiControllerLogging:
    def test_validate_success_logs_info(self, client, autotester_caplog):
        from test_ai_manager import FakeOllama

        ai = client.application.extensions["ai_manager"]
        ai.ollama = FakeOllama()
        client.post(
            "/ai/validate", data="{}", content_type="application/json"
        )
        messages = [r.message for r in autotester_caplog.records]
        assert any("Ollama reachable" in m for m in messages)


class TestAiManagerLogging:
    def test_digest_logs_start_and_finish(
        self, client, sample_pdf_bytes, autotester_caplog, temp_workspace
    ):
        """Build a project on disk and run digest; verify log lines."""
        from app.models.ai_manager import AIManager, OllamaUnavailable
        from app.models.config_manager import ConfigManager
        from app.models.file_manager import FileManager

        class _FakeOllama:
            def __init__(self):
                self.dim = 8

            def is_available(self):
                return True

            def embed(self, text, model):
                return [float(len(text) % 7) / 7.0] * self.dim

            def embed_batch(self, texts, model, batch_size=16):
                return [self.embed(t, model) for t in texts]

        # Build a project on disk with a sample PDF.
        fm = FileManager(temp_workspace["projects"])
        entry = fm.save_upload(io.BytesIO(sample_pdf_bytes), "doc.pdf", "logproj")
        pdf_path = fm.project_path(entry.name) / "doc.pdf"

        # Run digest with a fake Ollama client.
        cm = ConfigManager(temp_workspace["config"])
        ai = AIManager(cm, fm, ollama_client=_FakeOllama())
        ai.digest_pdf(entry.name, pdf_path)

        messages = [r.message for r in autotester_caplog.records]
        assert any("AI digest started" in m and entry.name in m for m in messages)
        assert any("AI digest finished" in m and entry.name in m for m in messages)


class TestJobRunnerLogging:
    def test_submit_and_failure_log(self, autotester_caplog):
        from app.services.job_runner import JobRunner

        runner = JobRunner(max_workers=1, ttl_seconds=5.0)

        def boom():
            raise RuntimeError("kaboom")

        job_id = runner.submit(boom)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if runner.get(job_id)["state"] == "error":
                break
            time.sleep(0.02)

        messages = [r.message for r in autotester_caplog.records]
        assert any(f"Job {job_id} submitted" in m for m in messages)
        assert any(f"Job {job_id} failed" in m and "RuntimeError" in m for m in messages)
        runner.shutdown()
