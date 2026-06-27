"""Tests for the autotester logger integration.

Verifies that key application events emit log records at the expected
level. Uses pytest's ``caplog`` fixture so we don't depend on stdout
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
    def test_upload_logs_info(self, client, sample_pdf_bytes, autotester_caplog):
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
        assert any("User uploaded PDF | Project: log_demo | File: doc.pdf" in m for m in messages)

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
        assert any("Project renamed | renamed -> renamed2" in m for m in messages)

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
        assert any("Project deleted | doomed" in m for m in messages)


class TestConfigControllerLogging:
    def test_config_save_logs_info(self, client, autotester_caplog):
        client.post("/config/", data={"theme": "dark"})
        messages = [r.message for r in autotester_caplog.records]
        assert any("Configuration saved by user" in m for m in messages)

    def test_config_save_logs_info_for_log_level(self, client, autotester_caplog):
        client.post("/config/", data={"log_level": "DEBUG"})
        messages = [r.message for r in autotester_caplog.records]
        assert any("Configuration saved by user" in m for m in messages)


class TestDigestionLogging:
    def test_per_page_digestion_logs(self, client, sample_pdf_bytes, autotester_caplog):
        """Upload a PDF with a real markdown file so the supervisor digests a page."""
        from test_ai_manager import FakeOllama

        client.application.extensions["ai_manager"].ollama = FakeOllama()
        client.post(
            "/files/upload",
            data={
                "project_name": "dpage",
                "pdf": (io.BytesIO(sample_pdf_bytes), "doc.pdf"),
            },
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        # Let the supervisor process a page.
        supervisor = client.application.extensions["digest_supervisor"]
        supervisor.wait_until_idle(timeout=5.0)
        messages = [r.message for r in autotester_caplog.records]
        assert any("Starting digestion" in m and "dpage" in m for m in messages)
        assert any("Finished digestion" in m and "dpage" in m for m in messages)


class TestJobRunnerLogging:
    def test_submit_and_success_log(self, autotester_caplog):
        from app.services.job_runner import JobRunner

        runner = JobRunner(max_workers=1, ttl_seconds=5.0)

        def happy():
            return "ok"

        job_id = runner.submit(happy)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if runner.get(job_id)["state"] == "done":
                break
            time.sleep(0.02)

        messages = [r.message for r in autotester_caplog.records]
        assert any(f"Job {job_id} started:" in m for m in messages)
        assert any(f"Job {job_id} completed | Status: SUCCESS" in m for m in messages)
        runner.shutdown()

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
        assert any(f"Job {job_id} started:" in m for m in messages)
        assert any(f"Job {job_id} completed | Status: ERROR" in m for m in messages)
        runner.shutdown()
