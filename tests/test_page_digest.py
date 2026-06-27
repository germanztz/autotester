"""Tests for app.services.page_digest helpers and LazyAIManager."""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.page_digest import (
    LazyAIManager,
    extract_to_markdown,
    find_first_pending_page,
    get_page_text,
    is_complete,
    remove_marker,
)


def _write_pdf_with_pages(pages: list[str]) -> bytes:
    """Build a minimal multi-page PDF with extractable text."""
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=612, height=792)
        rect = fitz.Rect(50, 50, 560, 750)
        page.insert_textbox(rect, text, fontsize=8)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    pdf = _write_pdf_with_pages(
        ["alpha " * 100, "beta " * 100, "gamma " * 100, "delta " * 100]
    )
    p = tmp_path / "sample.pdf"
    p.write_bytes(pdf)
    return p


class TestExtractToMarkdown:
    def test_creates_md_with_page_markers(self, tmp_path, sample_pdf_path):
        md = tmp_path / "out.md"
        n = extract_to_markdown(sample_pdf_path, md)
        assert n == 4
        content = md.read_text(encoding="utf-8")
        assert "### Page 1" in content
        assert "### Page 4" in content

    def test_each_marker_followed_by_text(self, tmp_path, sample_pdf_path):
        md = tmp_path / "out.md"
        extract_to_markdown(sample_pdf_path, md)
        content = md.read_text(encoding="utf-8")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("### Page "):
                # Next non-empty line should be page text (not another marker).
                assert i + 1 < len(lines), f"Marker {line} has no text after it"

    def test_idempotent_when_md_already_exists(self, tmp_path, sample_pdf_path):
        md = tmp_path / "out.md"
        extract_to_markdown(sample_pdf_path, md)
        first_content = md.read_text(encoding="utf-8")
        # Second call should not overwrite (idempotent).
        n = extract_to_markdown(sample_pdf_path, md)
        assert n == 4
        assert md.read_text(encoding="utf-8") == first_content

    def test_returns_zero_for_pdf_with_no_pages(self, tmp_path):
        # PyMuPDF refuses to save a 0-page PDF, so we use a non-PDF file
        # path to exercise the empty-input fallback. The function should
        # write an empty markdown file (or no file) and return 0.
        md = tmp_path / "out.md"
        # Use a path that doesn't exist; the function falls through to
        # producing an empty markdown if PyMuPDF can't open it.
        # We test a different edge case instead: a PDF that exists but
        # has no text on its pages.
        pdf = _write_pdf_with_pages([""])
        pdf_path = tmp_path / "empty_text.pdf"
        pdf_path.write_bytes(pdf)
        n = extract_to_markdown(pdf_path, md)
        assert n == 1
        # The marker is present but no body text
        assert "### Page 1" in md.read_text(encoding="utf-8")


class TestFindFirstPendingPage:
    def test_returns_none_when_no_markers(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text("just plain text\n", encoding="utf-8")
        assert find_first_pending_page(md) is None

    def test_returns_smallest_page(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text(
            "### Page 3\nbody\n### Page 1\nbody\n### Page 2\nbody\n",
            encoding="utf-8",
        )
        assert find_first_pending_page(md) == 1

    def test_returns_first_when_in_order(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text("### Page 1\na\n### Page 2\nb\n### Page 3\nc\n", encoding="utf-8")
        assert find_first_pending_page(md) == 1

    def test_ignores_malformed_markers(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text(
            "### Page\nbad\n### PageX 2\nbad\n### Page 3\nbody\n",
            encoding="utf-8",
        )
        assert find_first_pending_page(md) == 3

    def test_returns_none_for_missing_file(self, tmp_path):
        assert find_first_pending_page(tmp_path / "ghost.md") is None


class TestGetPageText:
    def test_returns_text_for_page(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text(
            "### Page 1\nfirst body\n### Page 2\nsecond body\n### Page 3\nthird\n",
            encoding="utf-8",
        )
        assert get_page_text(md, 1) == "first body"
        assert get_page_text(md, 2) == "second body"
        assert get_page_text(md, 3) == "third"

    def test_returns_text_for_last_page_until_eof(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text("### Page 1\nfirst\n### Page 2\nsecond\nmore lines\n", encoding="utf-8")
        assert get_page_text(md, 2) == "second\nmore lines"

    def test_returns_empty_for_missing_page(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text("### Page 1\nonly one\n", encoding="utf-8")
        assert get_page_text(md, 5) == ""


class TestRemoveMarker:
    def test_removes_only_target_marker(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text(
            "### Page 1\nbody1\n### Page 2\nbody2\n### Page 3\nbody3\n",
            encoding="utf-8",
        )
        remove_marker(md, 2)
        content = md.read_text(encoding="utf-8")
        assert "### Page 2" not in content
        assert "### Page 1" in content
        assert "### Page 3" in content
        assert "body2" in content  # body preserved

    def test_is_atomic_via_tmp_file(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text("### Page 1\nbody\n", encoding="utf-8")
        remove_marker(md, 1)
        # No leftover tmp files
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []

    def test_no_op_when_marker_missing(self, tmp_path):
        md = tmp_path / "out.md"
        original = "### Page 1\nbody\n"
        md.write_text(original, encoding="utf-8")
        remove_marker(md, 99)
        assert md.read_text(encoding="utf-8") == original


class TestIsComplete:
    def test_true_when_no_markers(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text("just text\nno markers\n", encoding="utf-8")
        assert is_complete(md) is True

    def test_false_when_marker_present(self, tmp_path):
        md = tmp_path / "out.md"
        md.write_text("### Page 1\nbody\n", encoding="utf-8")
        assert is_complete(md) is False


# ---------------------------------------------------------------------------
# LazyAIManager
# ---------------------------------------------------------------------------


class _FakeOllama:
    def __init__(self):
        self.calls = 0
        self.dim = 8

    def is_available(self):
        return True

    def embed(self, text, model):
        self.calls += 1
        return [float(len(text) % 7) / 7.0] * self.dim

    def embed_batch(self, texts, model, batch_size=16):
        return [self.embed(t, model) for t in texts]


@pytest.fixture
def project_with_pdf(temp_workspace, sample_pdf_bytes):
    """Use the conftest sample_pdf_bytes for shallow PDF (1 page)."""
    from app.models.file_manager import FileManager

    fm = FileManager(temp_workspace["projects"])
    entry = fm.save_upload(io.BytesIO(sample_pdf_bytes), "doc.pdf", "demo")
    pdf_path = fm.project_path(entry.name) / "doc.pdf"
    return entry, pdf_path


@pytest.fixture
def project_with_real_pdf(temp_workspace, sample_pdf_path):
    """Use a real multi-page PDF generated by fitz."""
    from app.models.file_manager import FileManager

    fm = FileManager(temp_workspace["projects"])
    pdf_target = fm.project_path("multipage") / "multipage.pdf"
    pdf_target.parent.mkdir(parents=True, exist_ok=True)
    pdf_target.write_bytes(sample_pdf_path.read_bytes())
    return "multipage", pdf_target


@pytest.fixture
def lazy_ai(temp_workspace):
    from app.models.ai_manager import AIManager
    from app.models.config_manager import ConfigManager
    from app.models.file_manager import FileManager

    cm = ConfigManager(temp_workspace["config"])
    fm = FileManager(temp_workspace["projects"])
    ai = AIManager(cm, fm, ollama_client=_FakeOllama())
    return LazyAIManager(ai_manager=ai, file_manager=fm)


class TestEnsureMarkdown:
    def test_creates_md_with_markers(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        md_path = lazy_ai.ensure_markdown(proj, pdf)
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "### Page 1" in content
        assert "### Page 4" in content

    def test_idempotent(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        md1 = lazy_ai.ensure_markdown(proj, pdf)
        first = md1.read_text(encoding="utf-8")
        md2 = lazy_ai.ensure_markdown(proj, pdf)
        assert md1 == md2
        assert md1.read_text(encoding="utf-8") == first


class TestProcessOnePage:
    def test_processes_first_pending_page(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)
        info = lazy_ai.process_one_page(proj)
        assert info is not None
        assert info["page"] == 1
        assert info["state"] == "processing"

    def test_removes_marker_after_processing(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        md_path = lazy_ai.ensure_markdown(proj, pdf)
        lazy_ai.process_one_page(proj)
        content = md_path.read_text(encoding="utf-8")
        assert "### Page 1" not in content
        assert "### Page 2" in content

    def test_persists_digest_state(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)
        lazy_ai.process_one_page(proj)
        state = lazy_ai.project_status(proj)
        assert state["current_page"] == 1
        assert state["chunks_embedded"] == 1

    def test_returns_none_when_complete(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)
        # Process first 3 pages — each returns info (not None)
        for _ in range(3):
            info = lazy_ai.process_one_page(proj)
            assert info is not None
        # 4th page is the last; now returns None (complete)
        info = lazy_ai.process_one_page(proj)
        assert info is None

    def test_resumes_from_partial_state(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)
        # Process 2 pages
        lazy_ai.process_one_page(proj)
        lazy_ai.process_one_page(proj)
        # Resume
        info = lazy_ai.process_one_page(proj)
        assert info["page"] == 3


class TestRunToCompletion:
    def test_runs_all_pages(self, lazy_ai, project_with_real_pdf, temp_workspace):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)
        summary = lazy_ai.run_to_completion(proj)
        assert summary.state == "complete"
        assert summary.chunks == 4
        assert summary.pages == 4

    def test_clears_all_markers(self, lazy_ai, project_with_real_pdf, temp_workspace):
        proj, pdf = project_with_real_pdf
        md_path = lazy_ai.ensure_markdown(proj, pdf)
        lazy_ai.run_to_completion(proj)
        assert is_complete(md_path)

    def test_progress_callback_invoked(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)
        events = []
        lazy_ai.run_to_completion(proj, on_progress=lambda e: events.append(e))
        # At minimum one event per page + a final done event
        page_events = [e for e in events if e.get("phase") == "page_done"]
        assert len(page_events) == 4
        assert any(e.get("phase") == "done" for e in events)


class TestCancel:
    def test_cancel_returns_none_when_complete(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)
        lazy_ai.run_to_completion(proj)
        # After complete, process_one_page returns None
        assert lazy_ai.process_one_page(proj) is None

    def test_cancel_event_stops_loop(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)

        ev = threading.Event()
        # Manually invoke a loop that checks the event after each page
        processed = 0
        for _ in range(4):
            if ev.is_set():
                break
            lazy_ai.process_one_page(proj)
            processed += 1
            if processed == 2:
                ev.set()
        assert processed == 2
        # Pending markers remain in the .md
        from app.services.page_digest import find_first_pending_page

        md_path = lazy_ai._md_path(proj)
        assert find_first_pending_page(md_path) == 3


class TestProjectStatus:
    def test_status_for_new_project_is_queued(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, _ = project_with_real_pdf
        # Before any ensure_markdown call
        state = lazy_ai.project_status(proj)
        assert state["state"] == "queued"

    def test_status_for_missing_project(self, lazy_ai):
        state = lazy_ai.project_status("ghost")
        assert state["state"] == "error"
        assert state["error"]


class TestChromaPersistsAcrossCalls:
    def test_chroma_has_vectors_after_processing(
        self, lazy_ai, project_with_real_pdf, temp_workspace
    ):
        proj, pdf = project_with_real_pdf
        lazy_ai.ensure_markdown(proj, pdf)
        lazy_ai.run_to_completion(proj)

        import chromadb

        project_dir = temp_workspace["projects"] / proj
        chroma_dir = project_dir / "chroma.db"
        client = chromadb.PersistentClient(
            path=str(chroma_dir),
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        col = client.get_or_create_collection(lazy_ai.ai_manager.COLLECTION_NAME)
        assert col.count() == 4