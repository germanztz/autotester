"""Tests for app.models.semantic_segmenter."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from app.models.semantic_segmenter import (
    SemanticRecord,
    SemanticSegmenter,
    _chunk_text_by_words,
    _parse_llm_response,
)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


class TestChunkTextByWords:
    def test_raises_on_zero_chunk_size(self):
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            _chunk_text_by_words("hello world", 0, 0)

    def test_raises_on_overlap_ge_size(self):
        with pytest.raises(ValueError, match="chunk_overlap must be >= 0 and < chunk_size"):
            _chunk_text_by_words("hello world", 5, 5)

    def test_empty_text_returns_empty(self):
        assert _chunk_text_by_words("", 10, 2) == []

    def test_single_chunk_when_text_smaller_than_size(self):
        chunks = _chunk_text_by_words("one two three", 10, 2)
        assert len(chunks) == 1
        text, start, end = chunks[0]
        assert text == "one two three"
        assert start == 0
        assert end == 3

    def test_multiple_chunks_with_overlap(self):
        text = " ".join(f"word{i}" for i in range(10))
        chunks = _chunk_text_by_words(text, 4, 1)
        assert len(chunks) >= 2
        # Verify overlap: second chunk starts before first chunk ends
        _, _, first_end = chunks[0]
        _, second_start, _ = chunks[1]
        assert second_start < first_end

    def test_chunks_cover_all_words(self):
        text = " ".join(f"w{i}" for i in range(100))
        chunks = _chunk_text_by_words(text, 12, 3)
        all_words = set()
        for _, start, end in chunks:
            for i in range(start, end):
                all_words.add(i)
        assert all_words == set(range(100))


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------


class TestParseLLMResponse:
    def test_parses_valid_json(self):
        raw = '{"original_text": "grouped text", "text_keywords": ["kw1", "kw2"]}'
        data = _parse_llm_response(raw)
        assert data["original_text"] == "grouped text"
        assert data["text_keywords"] == ["kw1", "kw2"]

    def test_strips_markdown_code_fence(self):
        raw = '```json\n{"original_text": "hello", "text_keywords": ["kw"]}\n```'
        data = _parse_llm_response(raw)
        assert data["original_text"] == "hello"

    def test_strips_markdown_code_fence_no_lang(self):
        raw = '```\n{"original_text": "hello", "text_keywords": ["kw"]}\n```'
        data = _parse_llm_response(raw)
        assert data["original_text"] == "hello"

    def test_raises_on_missing_original_text(self):
        raw = '{"text_keywords": ["kw"]}'
        with pytest.raises(ValueError, match="missing 'original_text'"):
            _parse_llm_response(raw)

    def test_raises_on_missing_text_keywords(self):
        raw = '{"original_text": "hello"}'
        with pytest.raises(ValueError, match="missing 'text_keywords'"):
            _parse_llm_response(raw)

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_llm_response("not json")


# ---------------------------------------------------------------------------
# SemanticRecord
# ---------------------------------------------------------------------------


class TestSemanticRecord:
    def test_to_dict(self):
        r = SemanticRecord(original_text="hello", text_keywords=["kw"], last_index=5)
        d = r.to_dict()
        assert d["original_text"] == "hello"
        assert d["text_keywords"] == ["kw"]
        assert d["last_index"] == 5


# ---------------------------------------------------------------------------
# Fake Ollama chat client for integration tests
# ---------------------------------------------------------------------------


class FakeOllamaChat:
    """Drop-in for OllamaChatClient that returns canned responses."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, str, str | None]] = []  # (model, prompt, system)

    def is_available(self) -> bool:
        return not self.fail

    def warmup(self, model: str) -> bool:
        return not self.fail

    def generate(self, model: str, prompt: str, system: str | None = None) -> str:
        self.calls.append((model, prompt, system))
        if self.fail:
            from app.models.llm_client import OllamaUnavailable
            raise OllamaUnavailable("Ollama down")
        # Extract first 3 words from prompt as keywords
        words = prompt.split()
        keywords = [w.strip('",.!?;:') for w in words[1:4] if w.strip('",.!?;:')]
        return json.dumps({
            "original_text": prompt,
            "text_keywords": keywords,
        })


@pytest.fixture
def fake_llm() -> FakeOllamaChat:
    return FakeOllamaChat()


@pytest.fixture
def segmenter(temp_workspace: dict, fake_llm: FakeOllamaChat):
    from app.models.config_manager import ConfigManager
    from app.models.file_manager import FileManager

    cm = ConfigManager(temp_workspace["config"])
    fm = FileManager(temp_workspace["projects"])
    return SemanticSegmenter(config_manager=cm, file_manager=fm, llm_client=fake_llm)


# ---------------------------------------------------------------------------
# SemanticSegmenter
# ---------------------------------------------------------------------------


class TestSemanticSegmenter:
    def test_get_ia_settings_returns_defaults(self, segmenter: SemanticSegmenter):
        settings = segmenter._get_ia_settings()
        assert settings["ollama_url"] == "http://localhost:11434"
        assert settings["ollama_model"] == "qwen3.5:latest"
        assert settings["chunk_size"] == 400
        assert settings["chunk_overlap"] == 50

    def test_get_ia_settings_uses_persisted_values(
        self, temp_workspace: dict, fake_llm: FakeOllamaChat
    ):
        from app.models.config_manager import ConfigManager
        from app.models.file_manager import FileManager

        cm = ConfigManager(temp_workspace["config"])
        cm.update_ia(chunk_size=100, chunk_overlap=10, ollama_model="test-model")
        fm = FileManager(temp_workspace["projects"])
        seg = SemanticSegmenter(cm, fm, llm_client=fake_llm)
        settings = seg._get_ia_settings()
        assert settings["chunk_size"] == 100
        assert settings["chunk_overlap"] == 10
        assert settings["ollama_model"] == "test-model"

    def test_validate_ollama_reachable(self, temp_workspace: dict, fake_llm: FakeOllamaChat):
        from unittest.mock import patch

        from app.models.config_manager import ConfigManager
        from app.models.file_manager import FileManager

        cm = ConfigManager(temp_workspace["config"])
        fm = FileManager(temp_workspace["projects"])
        seg = SemanticSegmenter(cm, fm, llm_client=fake_llm)
        with patch("app.models.llm_client.OllamaChatClient.is_available", return_value=True):
            ok, msg = seg.validate_ollama()
        assert ok is True
        assert "reachable" in msg

    def test_validate_ollama_unreachable(self, temp_workspace: dict):
        from app.models.config_manager import ConfigManager
        from app.models.file_manager import FileManager

        cm = ConfigManager(temp_workspace["config"])
        fm = FileManager(temp_workspace["projects"])
        seg = SemanticSegmenter(cm, fm, llm_client=FakeOllamaChat(fail=True))
        ok, msg = seg.validate_ollama()
        assert ok is False
        assert "not reachable" in msg

    def test_extract_text(self, tmp_path: Path):
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "Hello world")
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()

        from app.models.config_manager import ConfigManager
        from app.models.file_manager import FileManager

        cm = ConfigManager(tmp_path / "config.yaml")
        fm = FileManager(tmp_path / "projects")
        seg = SemanticSegmenter(cm, fm, llm_client=FakeOllamaChat())
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(buf.getvalue())
        text = seg.extract_text(pdf_path)
        assert "Hello world" in text

    def test_chunk_text(self, segmenter: SemanticSegmenter):
        text = " ".join(f"word{i}" for i in range(50))
        chunks = segmenter.chunk_text(text)
        assert len(chunks) >= 1
        # Default chunk_size=400, so 50 words should fit in one chunk
        assert len(chunks) == 1

        # Override config to smaller chunk size
        segmenter.config_manager.update_ia(chunk_size=10, chunk_overlap=2)
        chunks = segmenter.chunk_text(text)
        assert len(chunks) >= 5

    def test_process_chunk(self, segmenter: SemanticSegmenter, fake_llm: FakeOllamaChat):
        text = "the quick brown fox jumps over the lazy dog"
        grouped, keywords = segmenter.process_chunk(text, "qwen3.5:latest")
        assert isinstance(grouped, str)
        assert isinstance(keywords, list)
        assert len(keywords) >= 1

    def test_ensure_text_cache_creates_txt(self, segmenter: SemanticSegmenter, tmp_path: Path):
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "cached text content")
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()

        from app.models.file_manager import FileManager

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(buf.getvalue())
        fm = FileManager(tmp_path / "projects")
        # Use raw segmenter; manually set file_manager's root
        segmenter.file_manager = fm
        text = segmenter.ensure_text_cache("testproj", pdf_path)
        assert "cached text content" in text
        # Verify cache file exists
        cache = fm.project_path("testproj") / "testproj.txt"
        assert cache.exists()

    def test_ensure_text_cache_idempotent(self, segmenter: SemanticSegmenter, tmp_path: Path):
        from app.models.file_manager import FileManager

        fm = FileManager(tmp_path / "projects")
        segmenter.file_manager = fm
        cache = fm.project_path("testproj") / "testproj.txt"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("existing content", encoding="utf-8")
        text = segmenter.ensure_text_cache("testproj", tmp_path / "ghost.pdf")
        assert text == "existing content"



