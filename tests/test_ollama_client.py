"""Tests for app.models.ai_manager.OllamaClient."""
from __future__ import annotations

import json

import pytest
import requests
import responses

from app.models.ai_manager import OllamaClient, OllamaUnavailable


BASE = "http://localhost:11434"


@pytest.fixture
def client() -> OllamaClient:
    return OllamaClient(base_url=BASE, timeout=2.0)


class TestIsAvailable:
    @responses.activate
    def test_returns_true_on_200(self, client: OllamaClient):
        responses.add(responses.GET, f"{BASE}/api/tags", json={"models": []}, status=200)
        assert client.is_available() is True

    @responses.activate
    def test_returns_false_on_500(self, client: OllamaClient):
        responses.add(responses.GET, f"{BASE}/api/tags", json={"error": "boom"}, status=500)
        assert client.is_available() is False

    @responses.activate
    def test_returns_false_on_connection_error(self, client: OllamaClient):
        responses.add(
            responses.GET,
            f"{BASE}/api/tags",
            body=requests.exceptions.ConnectionError("refused"),
        )
        assert client.is_available() is False


class TestEmbed:
    @responses.activate
    def test_returns_embedding_vector(self, client: OllamaClient):
        responses.add(
            responses.POST,
            f"{BASE}/api/embeddings",
            json={"embedding": [0.1, 0.2, 0.3]},
            status=200,
        )
        vec = client.embed("hello", model="qwen3-embedding:4b")
        assert vec == [0.1, 0.2, 0.3]
        body = json.loads(responses.calls[0].request.body)
        assert body == {"model": "qwen3-embedding:4b", "prompt": "hello"}

    @responses.activate
    def test_raises_on_missing_embedding_key(self, client: OllamaClient):
        responses.add(
            responses.POST,
            f"{BASE}/api/embeddings",
            json={"error": "bad model"},
            status=200,
        )
        with pytest.raises(OllamaUnavailable):
            client.embed("hello", model="qwen3-embedding:4b")

    @responses.activate
    def test_raises_on_http_error(self, client: OllamaClient):
        responses.add(
            responses.POST,
            f"{BASE}/api/embeddings",
            json={"error": "not found"},
            status=404,
        )
        with pytest.raises(OllamaUnavailable):
            client.embed("hello", model="qwen3-embedding:4b")

    @responses.activate
    def test_raises_on_connection_error(self, client: OllamaClient):
        responses.add(
            responses.POST,
            f"{BASE}/api/embeddings",
            body=requests.exceptions.ConnectionError("refused"),
        )
        with pytest.raises(OllamaUnavailable):
            client.embed("hello", model="qwen3-embedding:4b")


class TestEmbedBatch:
    @responses.activate
    def test_embeds_multiple_texts_in_order(self, client: OllamaClient):
        # First call: probe /api/embed (plural) -> 404 -> fall back to legacy
        responses.add(
            responses.POST,
            f"{BASE}/api/embed",
            json={"error": "not found"},
            status=404,
        )
        # Then 3 legacy calls, one per text
        for i in range(3):
            responses.add(
                responses.POST,
                f"{BASE}/api/embeddings",
                json={"embedding": [float(i), float(i + 1)]},
                status=200,
            )
        vectors = client.embed_batch(["a", "b", "c"], model="m", batch_size=2)
        assert vectors == [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]]
        # 1 probe (404) + 3 legacy = 4
        assert len(responses.calls) == 4

    def test_rejects_invalid_batch_size(self, client: OllamaClient):
        with pytest.raises(ValueError):
            client.embed_batch(["a"], model="m", batch_size=0)


class TestInit:
    def test_strips_trailing_slash(self):
        c = OllamaClient(base_url="http://localhost:11434/")
        assert c.base_url == "http://localhost:11434"