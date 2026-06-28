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
    _parse_keywords_response,
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
# Keywords response parsing
# ---------------------------------------------------------------------------


class TestParseKeywordsResponse:
    def test_parses_valid_json(self):
        raw = '{"text_keywords": ["kw1", "kw2"]}'
        keywords = _parse_keywords_response(raw)
        assert keywords == ["kw1", "kw2"]

    def test_strips_markdown_code_fence(self):
        raw = '```json\n{"text_keywords": ["kw"]}\n```'
        keywords = _parse_keywords_response(raw)
        assert keywords == ["kw"]

    def test_strips_markdown_code_fence_no_lang(self):
        raw = '```\n{"text_keywords": ["kw"]}\n```'
        keywords = _parse_keywords_response(raw)
        assert keywords == ["kw"]

    def test_raises_on_missing_text_keywords(self):
        raw = '{"original_text": "hello"}'
        with pytest.raises(ValueError, match="missing 'text_keywords'"):
            _parse_keywords_response(raw)

    def test_accepts_empty_keywords(self):
        raw = '{"text_keywords": []}'
        keywords = _parse_keywords_response(raw)
        assert keywords == []

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_keywords_response("not json")


# ---------------------------------------------------------------------------
# SemanticRecord
# ---------------------------------------------------------------------------


class TestSemanticRecord:
    def test_to_dict(self):
        r = SemanticRecord(original_text="hello", text_keywords=["kw"])
        d = r.to_dict()
        assert d["original_text"] == "hello"
        assert d["text_keywords"] == ["kw"]

    def test_to_dict_with_none_keywords(self):
        r = SemanticRecord(original_text="hello", text_keywords=None)
        d = r.to_dict()
        assert d["original_text"] == "hello"
        assert d["text_keywords"] is None


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

    def generate(self, model: str, prompt: str, system: str | None = None, **kwargs: object) -> str:
        self.calls.append((model, prompt, system))
        if self.fail:
            from app.models.llm_client import OllamaUnavailable
            raise OllamaUnavailable("Ollama down")
        words = prompt.split()
        keywords = [w.strip('",.!?;:') for w in words[1:4] if w.strip('",.!?;:')]
        return json.dumps({"text_keywords": keywords})


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
        assert settings["chunk_size"] == 100
        assert settings["chunk_overlap"] == 10

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
        assert len(chunks) == 1

        segmenter.config_manager.update_ia(chunk_size=10, chunk_overlap=2)
        chunks = segmenter.chunk_text(text)
        assert len(chunks) >= 5

    def test_extract_keywords(self, segmenter: SemanticSegmenter, fake_llm: FakeOllamaChat):
        text = "the quick brown fox jumps over the lazy dog"
        keywords = segmenter.extract_keywords(text, "qwen3.5:latest")
        assert isinstance(keywords, list)
        assert len(keywords) >= 1

    def test_ensure_text_cache_returns_text(self, segmenter: SemanticSegmenter, tmp_path: Path):
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
        segmenter.file_manager = fm
        text = segmenter.ensure_text_cache("testproj", pdf_path)
        assert "cached text content" in text

    def test_ensure_text_cache_re_extracts(self, segmenter: SemanticSegmenter, tmp_path: Path):
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "hello world")
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()

        from app.models.file_manager import FileManager

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(buf.getvalue())
        fm = FileManager(tmp_path / "projects")
        segmenter.file_manager = fm
        text = segmenter.ensure_text_cache("testproj", pdf_path)
        assert "hello world" in text

    def test_build_chunk_dicts(self, segmenter: SemanticSegmenter, tmp_path: Path):
        from app.models.file_manager import FileManager

        fm = FileManager(tmp_path / "projects")
        segmenter.file_manager = fm
        texts = ["chunk one text", "chunk two text", "chunk three text"]
        chunks = segmenter._build_chunk_dicts(texts)
        assert len(chunks) == 3
        assert chunks[0]["original_text"] == "chunk one text"
        assert chunks[0]["text_keywords"] is None
        assert chunks[0]["page_number"] is None

    def test_build_chunk_dicts_with_page_numbers(self, segmenter: SemanticSegmenter):
        texts = ["first chunk", "second chunk"]
        pnums = [1, 3]
        chunks = segmenter._build_chunk_dicts(texts, pnums)
        assert chunks[0]["page_number"] == 1
        assert chunks[1]["page_number"] == 3

    def test_extract_text_by_page(self, segmenter: SemanticSegmenter, tmp_path: Path):
        import fitz

        doc = fitz.open()
        page1 = doc.new_page(width=612, height=792)
        page1.insert_text((72, 72), "page one text")
        page2 = doc.new_page(width=612, height=792)
        page2.insert_text((72, 72), "page two content")
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(buf.getvalue())
        pages = segmenter.extract_text_by_page(pdf_path)
        assert len(pages) == 2
        assert pages[0][0] == 1
        assert "page one" in pages[0][1]
        assert pages[1][0] == 2
        assert "page two" in pages[1][1]

    def test_compute_page_word_ranges(self):
        pages = [(1, "hello world"), (2, "foo bar baz")]
        ranges = SemanticSegmenter._compute_page_word_ranges(pages)
        assert ranges == [(1, 0, 2), (2, 2, 5)]

    def test_page_number_from_word_index(self):
        ranges = [(1, 0, 10), (2, 10, 25), (3, 25, 40)]
        assert SemanticSegmenter._page_number_from_word_index(0, ranges) == 1
        assert SemanticSegmenter._page_number_from_word_index(9, ranges) == 1
        assert SemanticSegmenter._page_number_from_word_index(10, ranges) == 2
        assert SemanticSegmenter._page_number_from_word_index(24, ranges) == 2
        assert SemanticSegmenter._page_number_from_word_index(25, ranges) == 3
