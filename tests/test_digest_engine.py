"""Tests for app.services.digest_engine — LazyAIManager with semantic segmentation."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from app.services.digest_engine import DigestSummary, LazyAIManager


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Drop-in for OllamaChatClient. Counts calls and can be told to fail."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.call_count = 0
        self.calls: list[tuple[str, str, str | None]] = []

    def is_available(self) -> bool:
        return not self.fail

    def generate(self, model: str, prompt: str, system: str | None = None, **kwargs: object) -> str:
        self.call_count += 1
        self.calls.append((model, prompt, system))
        if self.fail:
            from app.models.llm_client import OllamaUnavailable
            raise OllamaUnavailable("Ollama down")
        words = prompt.split()
        keywords = [w.strip('",.!?;:') for w in words[1:4] if w.strip('",.!?;:')]
        return (
            '{"original_text": "grouped ' + " ".join(words[:5]) + '", '
            '"text_keywords": ' + json.dumps(keywords) + '}'
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pdf_with_text(text: str) -> bytes:
    """Build a single-page PDF with the given text."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    rect = fitz.Rect(50, 50, 560, 750)
    page.insert_textbox(rect, text, fontsize=8)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> _FakeLLM:
    return _FakeLLM()


@pytest.fixture
def segmenter_and_lazy(tmp_path: Path, fake_llm: _FakeLLM):
    """Build a SemanticSegmenter + LazyAIManager wired to a fake LLM.

    Uses ``tmp_path`` (not ``temp_workspace``) to avoid the autouse
    ``_shutdown_job_runner`` fixture creating a Flask app whose supervisor
    thread would scan the same projects directory and cause races.
    """
    import yaml

    from app.models.config_manager import ConfigManager
    from app.models.file_manager import FileManager
    from app.models.semantic_segmenter import SemanticSegmenter

    projects_dir = tmp_path / "projects"
    config_path = tmp_path / "config.yaml"
    projects_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump({"theme": "system", "app_name": "autotester"}))

    cm = ConfigManager(config_path)
    fm = FileManager(projects_dir)
    seg = SemanticSegmenter(config_manager=cm, file_manager=fm, llm_client=fake_llm, request_timeout=5.0)
    lazy = LazyAIManager(segmenter=seg, file_manager=fm)
    return {"cm": cm, "fm": fm, "seg": seg, "lazy": lazy, "fake": fake_llm}


@pytest.fixture
def project_with_pdf(segmenter_and_lazy: dict):
    """Create a project with a PDF that has extractable text."""
    fm = segmenter_and_lazy["fm"]
    lazy = segmenter_and_lazy["lazy"]
    text = "hello " * 60 + "world " * 60 + "test " * 60
    pdf_bytes = _write_pdf_with_text(text)
    entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "demo")
    pdf_path = fm.project_path(entry.name) / "doc.pdf"
    return entry, pdf_path, segmenter_and_lazy


# ---------------------------------------------------------------------------
# TestEnsureCache
# ---------------------------------------------------------------------------


class TestEnsureCache:
    def test_creates_txt_with_text(self, segmenter_and_lazy: dict):
        lazy = segmenter_and_lazy["lazy"]
        fm = segmenter_and_lazy["fm"]
        text = "alpha " * 40 + "beta " * 40
        pdf_bytes = _write_pdf_with_text(text)
        entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "cachedemo")
        pdf_path = fm.project_path(entry.name) / "doc.pdf"
        cached = lazy.ensure_cache(entry.name, pdf_path)
        assert "alpha" in cached
        assert "beta" in cached
        cache_path = fm.project_path(entry.name) / f"{entry.name}.txt"
        assert cache_path.exists()

    def test_idempotent(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, pdf_path, _ = project_with_pdf
        lazy = segmenter_and_lazy["lazy"] if isinstance(segmenter_and_lazy, dict) else segmenter_and_lazy
        lazy = _get_lazy(segmenter_and_lazy)
        first = lazy.ensure_cache(entry.name, pdf_path)
        second = lazy.ensure_cache(entry.name, pdf_path)
        assert first == second


def _get_lazy(d):
    return d["lazy"]


# ---------------------------------------------------------------------------
# TestGenerateTitle
# ---------------------------------------------------------------------------


class TestGenerateTitle:
    def test_generates_title(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        # ensure_cache first so the .txt file exists
        lazy.ensure_cache(entry.name, pdf_path)
        title = lazy.generate_title(entry.name)
        assert title != ""
        # the fake LLM returns text from the prompt — should be non-empty
        persisted = lazy._load_state(entry.name)
        assert persisted.get("title") == title

    def test_skips_when_title_exists(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        fake = components["fake"]
        lazy.ensure_cache(entry.name, pdf_path)
        lazy._persist_state(entry.name, title="existing-title")
        fake.call_count = 0
        title = lazy.generate_title(entry.name)
        assert title == "existing-title"
        assert fake.call_count == 0  # LLM was not called

    def test_returns_empty_when_no_cache(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        # Don't call ensure_cache — no .txt file exists
        title = lazy.generate_title(entry.name)
        assert title == ""

    def test_returns_empty_on_llm_failure(self, segmenter_and_lazy: dict):
        from tests.test_digest_engine import _FakeLLM
        lazy = segmenter_and_lazy["lazy"]
        fm = segmenter_and_lazy["fm"]
        # Create a project with an LLM that always fails
        failing_llm = _FakeLLM(fail=True)
        seg = segmenter_and_lazy["seg"]
        seg.llm = failing_llm
        text = "hello world " * 50
        pdf_bytes = _write_pdf_with_text(text)
        entry = fm.save_upload(io.BytesIO(pdf_bytes), "doc.pdf", "failtitle")
        pdf_path = fm.project_path(entry.name) / "doc.pdf"
        lazy.ensure_cache(entry.name, pdf_path)
        title = lazy.generate_title(entry.name)
        assert title == ""


# ---------------------------------------------------------------------------
# TestProcessOneChunk
# ---------------------------------------------------------------------------


class TestProcessOneChunk:
    def test_processes_first_chunk(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        # Use small chunks so we get multiple chunks
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        info = lazy.process_one_chunk(entry.name)
        assert info is not None
        assert info["chunk"] == 1
        assert info["state"] in ("processing", "complete")

    def test_persists_chunks_json(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)
        chunks_path = components["fm"].project_path(entry.name) / "chunks.json"
        assert chunks_path.exists()
        data = json.loads(chunks_path.read_text(encoding="utf-8"))
        assert len(data) >= 1
        assert "original_text" in data[0]
        assert "text_keywords" in data[0]
        assert "last_index" in data[0]

    def test_updates_digest_state(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        lazy.process_one_chunk(entry.name)
        state = lazy.project_status(entry.name)
        assert state["chunks_processed"] >= 1
        assert state["total_keywords"] >= 1
        assert state["last_index"] > 0

    def test_returns_none_when_complete(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        # Force small chunks so we get multiple chunks
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        # Process until None
        while True:
            info = lazy.process_one_chunk(entry.name)
            if info is None:
                break
        state = lazy.project_status(entry.name)
        assert state["state"] == "complete"

    def test_resumes_from_partial_state(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        # Process 2 chunks
        lazy.process_one_chunk(entry.name)
        lazy.process_one_chunk(entry.name)
        # Resume
        info = lazy.process_one_chunk(entry.name)
        assert info is not None
        assert info["chunk"] >= 3


# ---------------------------------------------------------------------------
# TestRunToCompletion
# ---------------------------------------------------------------------------


class TestRunToCompletion:
    def test_runs_all_chunks(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        summary = lazy.run_to_completion(entry.name)
        assert summary.state == "complete"
        assert summary.chunks > 0
        assert summary.keywords > 0

    def test_progress_callback_invoked(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        events = []
        lazy.run_to_completion(entry.name, on_progress=lambda e: events.append(e))
        chunk_events = [e for e in events if e.get("phase") == "chunk_done"]
        assert len(chunk_events) >= 1
        assert any(e.get("phase") == "done" for e in events)


# ---------------------------------------------------------------------------
# TestCancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_event_stops_loop(self, project_with_pdf):
        entry, pdf_path, components = project_with_pdf
        lazy = components["lazy"]
        seg = components["seg"]
        seg.config_manager.update_ia(chunk_size=30, chunk_overlap=5)
        lazy.ensure_cache(entry.name, pdf_path)
        # Simulate cancel after first chunk
        processed = 0
        for _ in range(10):
            if lazy.is_cancelled(entry.name):
                break
            if lazy.process_one_chunk(entry.name) is None:
                break
            processed += 1
            if processed == 1:
                lazy.cancel(entry.name)
        assert processed == 1


# ---------------------------------------------------------------------------
# TestProjectStatus
# ---------------------------------------------------------------------------


class TestProjectStatus:
    def test_new_project_is_queued(self, segmenter_and_lazy: dict, project_with_pdf):
        entry, _, _ = project_with_pdf
        lazy = segmenter_and_lazy["lazy"]
        state = lazy.project_status(entry.name)
        assert state["state"] == "queued"

    def test_missing_project(self, segmenter_and_lazy: dict):
        lazy = segmenter_and_lazy["lazy"]
        state = lazy.project_status("ghost")
        assert state["state"] == "error"
        assert state["error"]


# ---------------------------------------------------------------------------
# TestDigestSummary
# ---------------------------------------------------------------------------


class TestDigestSummary:
    def test_to_dict(self):
        s = DigestSummary(
            project_name="p",
            state="complete",
            chunks=5,
            keywords=12,
            duration_seconds=3.14,
            total_words=1000,
        )
        d = s.to_dict()
        assert d["project_name"] == "p"
        assert d["chunks"] == 5
        assert d["keywords"] == 12
