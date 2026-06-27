"""Tests for app.controllers.ai_controller routes."""
from __future__ import annotations

import io
import json
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


class TestStatusEndpoint:
    def test_returns_unknown_for_missing_job(self, client):
        response = client.get("/ai/status/nonexistent-id")
        assert response.status_code == 200
        data = response.get_json()
        assert data["state"] == "unknown"


class TestValidateEndpoint:
    def test_returns_ok_when_ollama_reachable(self, client):
        with patch(
            "app.models.llm_client.OllamaChatClient.is_available", return_value=True
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
            "app.models.llm_client.OllamaChatClient.is_available", return_value=False
        ):
            response = client.post(
                "/ai/validate",
                data=json.dumps({}),
                content_type="application/json",
            )
        assert response.status_code == 503
        assert response.get_json()["ok"] is False
