"""Tests for OllamaClient batch and retry behavior."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
import responses

from app.models.ai_manager import OllamaClient, OllamaUnavailable


BASE = "http://localhost:11434"


@pytest.fixture
def client() -> OllamaClient:
    return OllamaClient(base_url=BASE, timeout=2.0)


# ---------------------------------------------------------------------------
# Batch endpoint probing
# ---------------------------------------------------------------------------


class TestBatchProbe:
    @responses.activate
    def test_uses_modern_embed_endpoint_when_available(self, client: OllamaClient):
        # First call: probe /api/embed (plural)
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"embeddings": [[0.0]]},
            status=200,
        )
        # Second call: actual batch embedding
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]},
            status=200,
        )
        result = client.embed_batch(["a", "b"], model="m")
        assert result == [[0.1, 0.2], [0.3, 0.4]]
        assert len(responses.calls) == 2
        import json as _json

        # Verify the actual batch call (not the probe) sent the input array.
        batch_call = responses.calls[1]
        body = _json.loads(batch_call.request.body)
        assert body["model"] == "m"
        assert body["input"] == ["a", "b"]

    @responses.activate
    def test_falls_back_to_legacy_when_modern_returns_404(self, client: OllamaClient):
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"error": "not found"},
            status=404,
        )
        responses.add(
            responses.POST,
            f"{BASE}/api/embeddings",
            json={"embedding": [0.5, 0.6]},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE}/api/embeddings",
            json={"embedding": [0.7, 0.8]},
            status=200,
        )
        result = client.embed_batch(["x", "y"], model="m")
        assert result == [[0.5, 0.6], [0.7, 0.8]]
        # 1 probe (404) + 2 legacy calls = 3
        assert len(responses.calls) == 3
        assert client._batch_supported is False

    @responses.activate
    def test_does_not_reprobe_after_first_success(self, client: OllamaClient):
        # Probe + 2 batch calls
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"embeddings": [[0.0]]},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"embeddings": [[0.1]]},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"embeddings": [[0.2]]},
            status=200,
        )
        client.embed_batch(["a"], model="m")
        client.embed_batch(["b"], model="m")
        assert client._batch_supported is True


class TestSessionReuse:
    @responses.activate
    def test_reuses_session_across_calls(self, client: OllamaClient):
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"embeddings": [[0.0]]},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"embeddings": [[0.1]]},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"embeddings": [[0.2]]},
            status=200,
        )
        client.embed_batch(["a"], model="m")
        client.embed_batch(["b"], model="m")
        assert isinstance(client._session, requests.Session)


# ---------------------------------------------------------------------------
# Retry policy (uses is_available -> GET /api/tags)
# ---------------------------------------------------------------------------


class TestRetryOnConnectionError:
    @responses.activate
    def test_retries_connection_error_then_succeeds(self, client: OllamaClient):
        responses.add(
            responses.GET,
            f"{BASE}/api/tags",
            body=requests.exceptions.ConnectionError("refused"),
        )
        responses.add(
            responses.GET,
            f"{BASE}/api/tags",
            body=requests.exceptions.ConnectionError("refused"),
        )
        responses.add(responses.GET, f"{BASE}/api/tags", json={"models": []}, status=200)

        with patch("app.models.ai_manager.time.sleep") as sleep_mock:
            assert client.is_available() is True
        assert sleep_mock.call_count == 2
        sleep_mock.assert_any_call(1.0)
        sleep_mock.assert_any_call(2.0)

    @responses.activate
    def test_gives_up_after_three_attempts(self, client: OllamaClient):
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{BASE}/api/tags",
                body=requests.exceptions.ConnectionError("refused"),
            )
        with patch("app.models.ai_manager.time.sleep"):
            assert client.is_available() is False


class TestRetryOn5xx:
    @responses.activate
    def test_retries_500_then_succeeds(self, client: OllamaClient):
        responses.add(responses.GET, f"{BASE}/api/tags", json={"err": "x"}, status=500)
        responses.add(responses.GET, f"{BASE}/api/tags", json={"models": []}, status=200)
        with patch("app.models.ai_manager.time.sleep") as sleep_mock:
            assert client.is_available() is True
        sleep_mock.assert_called_once_with(1.0)

    @responses.activate
    def test_gives_up_after_three_503s(self, client: OllamaClient):
        for _ in range(3):
            responses.add(responses.GET, f"{BASE}/api/tags", json={}, status=503)
        with patch("app.models.ai_manager.time.sleep"):
            with pytest.raises(OllamaUnavailable) as exc_info:
                client._do_with_retry("GET", "/api/tags")
        assert "after 3 attempts" in str(exc_info.value)
        assert "503" in str(exc_info.value)


class TestNoRetryOn4xx:
    @responses.activate
    def test_does_not_retry_on_404(self, client: OllamaClient):
        responses.add(responses.GET, f"{BASE}/api/tags", json={"err": "x"}, status=404)
        with patch("app.models.ai_manager.time.sleep") as sleep_mock:
            with pytest.raises(OllamaUnavailable) as exc_info:
                client._do_with_retry("GET", "/api/tags")
        sleep_mock.assert_not_called()
        assert "404" in str(exc_info.value)

    @responses.activate
    def test_does_not_retry_on_400(self, client: OllamaClient):
        responses.add(responses.GET, f"{BASE}/api/tags", json={"err": "x"}, status=400)
        with patch("app.models.ai_manager.time.sleep") as sleep_mock:
            with pytest.raises(OllamaUnavailable):
                client._do_with_retry("GET", "/api/tags")
        sleep_mock.assert_not_called()


class TestRetryOnTimeout:
    @responses.activate
    def test_retries_timeout_then_succeeds(self, client: OllamaClient):
        responses.add(
            responses.GET,
            f"{BASE}/api/tags",
            body=requests.exceptions.Timeout("read timeout"),
        )
        responses.add(responses.GET, f"{BASE}/api/tags", json={"models": []}, status=200)
        with patch("app.models.ai_manager.time.sleep") as sleep_mock:
            assert client.is_available() is True
        sleep_mock.assert_called_once_with(1.0)


class TestBackoffTiming:
    @responses.activate
    def test_exponential_backoff_delays(self, client: OllamaClient):
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{BASE}/api/tags",
                body=requests.exceptions.ConnectionError("refused"),
            )
        delays: list[float] = []

        def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        with patch("app.models.ai_manager.time.sleep", side_effect=fake_sleep):
            client.is_available()
        assert delays == [1.0, 2.0]
