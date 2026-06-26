"""Tests for app.controllers.ai_controller routes."""
from __future__ import annotations

import io
import json
import time
from unittest.mock import patch

import pytest


def _make_text_pdf(text: str = "hello world this is test text " * 30) -> bytes:
    """Build a tiny in-memory PDF with extractable text."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), text)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def text_pdf_bytes() -> bytes:
    return _make_text_pdf()


def _wait_done(client, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/ai/status/{job_id}")
        last = resp.get_json()
        if last.get("state") in ("done", "error"):
            return last
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} never finished: {last}")


class TestStatusEndpoint:
    def test_returns_unknown_for_missing_job(self, client):
        response = client.get("/ai/status/nonexistent-id")
        assert response.status_code == 200
        data = response.get_json()
        assert data["state"] == "unknown"


class TestValidateEndpoint:
    def test_returns_ok_when_ollama_reachable(self, client):
        with patch(
            "app.models.ai_manager.OllamaClient.is_available", return_value=True
        ):
            response = client.post(
                "/ai/validate",
                data=json.dumps({}),
                content_type="application/json",
            )
        assert response.status_code == 200
        assert response.get_json()["ok"] is True

    def test_returns_503_when_ollama_down(self, client):
        with patch(
            "app.models.ai_manager.OllamaClient.is_available", return_value=False
        ):
            response = client.post(
                "/ai/validate",
                data=json.dumps({}),
                content_type="application/json",
            )
        assert response.status_code == 503
        assert response.get_json()["ok"] is False


class TestUploadEnqueuesJob:
    def test_upload_returns_202_with_job_id(
        self, client, text_pdf_bytes: bytes
    ):
        from test_ai_manager import FakeOllama

        ai = client.application.extensions["ai_manager"]
        ai.ollama = FakeOllama()

        data = {
            "project_name": "async_demo",
            "pdf": (io.BytesIO(text_pdf_bytes), "doc.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 202
        payload = response.get_json()
        assert "job_id" in payload
        assert payload["project"] == "async_demo"

    def test_polling_returns_done_with_summary(
        self, client, text_pdf_bytes: bytes
    ):
        from test_ai_manager import FakeOllama

        ai = client.application.extensions["ai_manager"]
        ai.ollama = FakeOllama()

        data = {
            "project_name": "poll_demo",
            "pdf": (io.BytesIO(text_pdf_bytes), "doc.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        job_id = response.get_json()["job_id"]

        final = _wait_done(client, job_id)
        assert final["state"] == "done"
        assert final["result"]["project_name"] == "poll_demo"
        assert final["result"]["chunks"] >= 1

    def test_upload_rejects_non_pdf_with_400(self, client):
        from test_ai_manager import FakeOllama

        ai = client.application.extensions["ai_manager"]
        ai.ollama = FakeOllama()

        data = {
            "project_name": "bad",
            "pdf": (io.BytesIO(b"not a pdf"), "fake.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400
        assert "error" in response.get_json()