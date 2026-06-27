"""Tests for app.models.llm_client.OllamaChatClient using mocks."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock, patch

import pytest
import requests

from app.models.llm_client import OllamaChatClient, OllamaUnavailable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_response(
    status: int = 200,
    json_data: dict[str, Any] | None = None,
    elapsed: float = 0.1,
) -> Mock:
    resp = Mock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.elapsed.total_seconds.return_value = elapsed
    resp.text = json.dumps(json_data) if json_data else ""
    return resp


def _patch_session(mock_request: Mock, response: Mock) -> Mock:
    mock_request.return_value = response
    return mock_request


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_returns_content_string(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)
        content = '{"key": "value"}'
        resp = _build_response(
            json_data={"message": {"role": "assistant", "content": content}},
        )

        with patch.object(client._session, "request", return_value=resp):
            result = client.generate("test-model", "hello")

        assert result == content

    def test_includes_system_prompt_in_messages(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)
        content = '{"key": "value"}'
        resp = _build_response(
            json_data={"message": {"role": "assistant", "content": content}},
        )

        with patch.object(client._session, "request", return_value=resp) as mock_req:
            client.generate("test-model", "hello", system="You are helpful.")

        call_body = mock_req.call_args[1]["json"]
        assert len(call_body["messages"]) == 2
        assert call_body["messages"][0]["role"] == "system"
        assert call_body["messages"][0]["content"] == "You are helpful."

    def test_raises_on_missing_message_key(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)
        resp = _build_response(json_data={"done": True})

        with patch.object(client._session, "request", return_value=resp):
            with pytest.raises(OllamaUnavailable, match="missing 'message.content'"):
                client.generate("test-model", "hello")

    def test_raises_on_missing_content_key(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)
        resp = _build_response(
            json_data={"message": {"role": "assistant"}},
        )

        with patch.object(client._session, "request", return_value=resp):
            with pytest.raises(OllamaUnavailable, match="missing 'message.content'"):
                client.generate("test-model", "hello")

    def test_accepts_empty_content(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)
        resp = _build_response(
            json_data={"message": {"role": "assistant", "content": ""}},
        )

        with patch.object(client._session, "request", return_value=resp):
            result = client.generate("test-model", "hello")

        assert result == ""


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_returns_true_when_ollama_reachable(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)
        resp = _build_response(status=200, json_data={"models": []})

        with patch.object(client._session, "request", return_value=resp):
            assert client.is_available() is True

    def test_returns_false_on_connection_error(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)

        with patch.object(
            client._session,
            "request",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            assert client.is_available() is False

    def test_returns_false_on_timeout(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)

        with patch.object(
            client._session,
            "request",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            assert client.is_available() is False


# ---------------------------------------------------------------------------
# warmup()
# ---------------------------------------------------------------------------


class TestWarmup:
    def test_returns_true_on_success(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)
        resp = _build_response(
            json_data={"message": {"role": "assistant", "content": "ok"}},
        )

        with patch.object(client._session, "request", return_value=resp):
            assert client.warmup("test-model") is True

    def test_returns_false_on_error(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=1)

        with patch.object(
            client._session,
            "request",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            assert client.warmup("test-model") is False


# ---------------------------------------------------------------------------
# Error handling & retries
# ---------------------------------------------------------------------------


class TestErrors:
    def test_timeout_raises_immediately(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=3)

        with patch.object(
            client._session,
            "request",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            with pytest.raises(OllamaUnavailable, match="timed out"):
                client.generate("m", "hello")

    def test_connection_error_retries_then_raises(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=3, backoff_base=0.01)

        with patch.object(
            client._session,
            "request",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ) as mock_req:
            with pytest.raises(OllamaUnavailable, match="unreachable"):
                client.generate("m", "hello")

        assert mock_req.call_count == 3

    def test_http_500_retries_then_raises(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=3, backoff_base=0.01)
        resp = _build_response(status=500)

        with patch.object(client._session, "request", return_value=resp) as mock_req:
            with pytest.raises(OllamaUnavailable, match="HTTP 500"):
                client.generate("m", "hello")

        assert mock_req.call_count == 3

    def test_http_400_raises_immediately_no_retry(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=3, backoff_base=0.01)
        resp = _build_response(status=404)

        with patch.object(client._session, "request", return_value=resp) as mock_req:
            with pytest.raises(OllamaUnavailable, match="HTTP 404"):
                client.generate("m", "hello")

        assert mock_req.call_count == 1

    def test_http_200_with_missing_content_raises_no_retry(self):
        client = OllamaChatClient(timeout=5.0, max_attempts=3, backoff_base=0.01)
        resp = _build_response(status=200, json_data={"done": True})

        with patch.object(client._session, "request", return_value=resp) as mock_req:
            with pytest.raises(OllamaUnavailable, match="missing"):
                client.generate("m", "hello")

        assert mock_req.call_count == 1
