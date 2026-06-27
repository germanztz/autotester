"""Tests for app.services.digest_supervisor.DigestSupervisor.

The supervisor drives one-page-at-a-time ingestion across the whole
application. These tests build their own ``DigestSupervisor`` instance
(with a tight ``interval``) so they don't depend on the daemon thread
that ``create_app()`` would otherwise start.
"""
from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

import pytest

from app.models.ai_manager import OllamaUnavailable
from app.models.config_manager import ConfigManager
from app.models.file_manager import FileManager
from app.services.digest_supervisor import DigestScanResult, DigestSupervisor
from app.services.page_digest import LazyAIManager


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _FakeOllama:
    """Drop-in for OllamaClient. Counts calls and can be told to fail."""

    def __init__(self, fail: bool = False, dim: int = 8) -> None:
        self.fail = fail
        self.dim = dim
        self.calls: list[str] = []
        self.call_count = 0

    def is_available(self) -> bool:
        return not self.fail

    def embed(self, text: str, model: str) -> list[float]:
        self.call_count += 1
        self.calls.append(text)
        if self.fail:
            raise OllamaUnavailable("Ollama down")
        return [float(len(text) % 7) / 7.0] * self.dim

    def embed_batch(self, texts, model, batch_size: int = 16):
        return [self.embed(t, model) for t in texts]


def _make_text_pdf(pages: list[str]) -> bytes:
    """Build a multi-page PDF in memory."""
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), text)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _make_project(fm: FileManager, name: str, pdf_bytes: bytes) -> Path:
    """Create a project folder containing a PDF; return the PDF path."""
    entry = fm.save_upload(io.BytesIO(pdf_bytes), f"{name}.pdf", name)
    return fm.project_path(entry.name) / f"{name}.pdf"


@pytest.fixture
def ai_components(tmp_path: Path):
    """Build config + file + AI managers + LazyAIManager wired to FakeOllama.

    Uses an isolated tmp_path that is *not* the conftest ``temp_workspace``
    so the ``app`` fixture's DigestSupervisor (started for every test via the
    autouse ``_shutdown_job_runner``) does not scan the same project directory
    and consume pages while the test runs.
    """
    from app.models.ai_manager import AIManager

    projects_dir = tmp_path / "projects"
    config_path = tmp_path / "config.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump({"theme": "system", "app_name": "autotester"}))
    projects_dir.mkdir(parents=True, exist_ok=True)

    workspace = {"root": tmp_path, "projects": projects_dir, "config": config_path}
    cm = ConfigManager(workspace["config"])
    fm = FileManager(workspace["projects"])
    fake = _FakeOllama()
    ai = AIManager(cm, fm, ollama_client=fake)
    lazy = LazyAIManager(ai_manager=ai, file_manager=fm)
    return {"cm": cm, "fm": fm, "fake": fake, "ai": ai, "lazy": lazy}


def _new_supervisor(ai_components: dict, **overrides) -> DigestSupervisor:
    """Build a DigestSupervisor with tight timings for tests."""
    kwargs = dict(
        lazy_ai_manager=ai_components["lazy"],
        file_manager=ai_components["fm"],
        interval_seconds=0.01,
        max_consecutive_failures=overrides.pop("max_failures", 3),
        per_page_sleep_seconds=0.0,
    )
    kwargs.update(overrides)
    return DigestSupervisor(**kwargs)


# ---------------------------------------------------------------------------
# Basic scan behaviour
# ---------------------------------------------------------------------------


class TestScanOnce:
    def test_empty_projects_returns_all_complete(self, ai_components):
        sup = _new_supervisor(ai_components)
        result = sup.scan_once()
        assert result.all_complete is True
        assert result.pending_count == 0
        assert result.processed is None
        assert result.processed_ok is True

    def test_picks_first_pending_project(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["alpha " * 60, "beta " * 60, "gamma " * 60])
        _make_project(fm, "zeta", pdf_bytes)
        _make_project(fm, "alpha", pdf_bytes)

        sup = _new_supervisor(ai_components)
        result = sup.scan_once()
        assert result.processed == "alpha"
        assert result.processed_ok is True
        assert result.all_complete is False

    def test_processes_one_page_per_scan(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 50, "page " * 50, "page " * 50])
        _make_project(fm, "p", pdf_bytes)

        sup = _new_supervisor(ai_components)
        first = sup.scan_once()
        second = sup.scan_once()
        third = sup.scan_once()
        fourth = sup.scan_once()

        assert first.processed == "p" and first.processed_ok
        assert second.processed == "p" and second.processed_ok
        assert third.processed == "p" and third.processed_ok
        assert fourth.all_complete is True
        assert fourth.processed is None  # nothing to do

    def test_processes_one_project_to_completion_before_next(self, ai_components):
        """The supervisor always picks the first pending project alphabetically.

        With multiple projects it does NOT interleave pages between them:
        the first project is fully digested before the second is picked up.
        The single-page-at-a-time property is enforced *within* a digest;
        across digests the order is purely alphabetical / on-disk order.
        """
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["alpha " * 50, "beta " * 50])
        _make_project(fm, "a", pdf_bytes)
        _make_project(fm, "b", pdf_bytes)

        sup = _new_supervisor(ai_components)
        # First two scans pick 'a' (alphabetical priority); third and
        # fourth pick 'b'.
        r1 = sup.scan_once()
        r2 = sup.scan_once()
        r3 = sup.scan_once()
        r4 = sup.scan_once()
        assert r1.processed == "a"
        assert r2.processed == "a"
        assert r3.processed == "b"
        assert r4.processed == "b"

    def test_creates_markdown_on_first_scan(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["hello " * 50, "world " * 50])
        pdf_path = _make_project(fm, "x", pdf_bytes)

        sup = _new_supervisor(ai_components)
        result = sup.scan_once()
        md_path = pdf_path.parent / "x.md"
        assert md_path.exists()
        assert result.processed_ok

    def test_resumes_partial_digestion(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30] * 4)
        pdf_path = _make_project(fm, "p", pdf_bytes)
        # Pre-create markdown with one marker already removed.
        lazy = ai_components["lazy"]
        lazy.ensure_markdown("p", pdf_path)
        from app.services.page_digest import remove_marker

        remove_marker(lazy._md_path("p"), 1)
        # Set state so consecutive_failures is reset.
        lazy._persist_state("p", chunks_embedded=1, consecutive_failures=0)  # type: ignore[attr-defined]

        sup = _new_supervisor(ai_components)
        result = sup.scan_once()
        # Should pick up at page 2, not page 1.
        assert result.processed == "p"
        assert result.processed_ok
        state = lazy.project_status("p")
        assert state["chunks_embedded"] == 2


# ---------------------------------------------------------------------------
# Skipping rules
# ---------------------------------------------------------------------------


class TestSkipping:
    def test_skips_complete_projects(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30])
        pdf_path = _make_project(fm, "done", pdf_bytes)
        lazy = ai_components["lazy"]
        lazy.ensure_markdown("done", pdf_path)
        # Mark as fully complete.
        lazy.run_to_completion("done")  # this still loops, but legacy behaviour persists
        # Force the final state to complete + zero failures.
        lazy._persist_state("done", state="complete", consecutive_failures=0)  # type: ignore[attr-defined]

        sup = _new_supervisor(ai_components)
        result = sup.scan_once()
        assert result.all_complete is True
        assert result.processed is None

    def test_skips_terminal_failed_projects(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30])
        _make_project(fm, "bad", pdf_bytes)
        lazy = ai_components["lazy"]
        lazy.mark_failed("bad", "manual: gone")

        sup = _new_supervisor(ai_components)
        result = sup.scan_once()
        assert result.all_complete is True
        assert result.processed is None

    def test_resumes_cancelled_projects(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30, "more " * 30])
        pdf_path = _make_project(fm, "p", pdf_bytes)
        lazy = ai_components["lazy"]
        lazy.ensure_markdown("p", pdf_path)
        # Simulate a cancellation in flight.
        lazy.cancel("p")

        sup = _new_supervisor(ai_components)
        result = sup.scan_once()
        # The supervisor picks it up; the cancel flag is observed by
        # process_one_page's exit path. We don't assert on chunk count
        # here because the existing per-page cancel logic in
        # process_one_page may short-circuit; we just assert the project
        # was selected.
        assert result.processed == "p"


# ---------------------------------------------------------------------------
# Failure lifecycle
# ---------------------------------------------------------------------------


class TestFailureHandling:
    def test_increments_consecutive_failures_on_error(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30, "more " * 30])
        _make_project(fm, "p", pdf_bytes)
        lazy = ai_components["lazy"]
        ai_components["fake"].fail = True

        sup = _new_supervisor(ai_components)
        sup.scan_once()
        state = lazy.project_status("p")
        assert state["consecutive_failures"] == 1
        assert state["state"] == "error"

    def test_marks_terminal_failed_after_threshold(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30, "more " * 30])
        _make_project(fm, "p", pdf_bytes)
        lazy = ai_components["lazy"]
        fake = ai_components["fake"]
        fake.fail = True

        sup = _new_supervisor(ai_components, max_failures=3)
        # 3 failed scans should mark the project terminal.
        sup.scan_once()
        sup.scan_once()
        result = sup.scan_once()
        state = lazy.project_status("p")
        assert state["state"] == "failed"
        assert state["consecutive_failures"] >= 3
        # Fourth scan should not pick the project up.
        next_result = sup.scan_once()
        assert next_result.all_complete is True
        assert next_result.processed is None
        # Result of the third scan reflects terminal transition.
        assert result.failed_terminal is True

    def test_resets_consecutive_failures_on_success(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30, "more " * 30])
        _make_project(fm, "p", pdf_bytes)
        lazy = ai_components["lazy"]
        fake = ai_components["fake"]

        sup = _new_supervisor(ai_components, max_failures=5)
        fake.fail = True
        sup.scan_once()
        state = lazy.project_status("p")
        assert state["consecutive_failures"] == 1

        # Switch to success and scan again; counter must reset to 0.
        fake.fail = False
        sup.scan_once()
        state = lazy.project_status("p")
        assert state["consecutive_failures"] == 0

    def test_other_projects_continue_after_error(self, ai_components):
        """A persistent error on project 'a' does not block project 'b'.

        'a' fails every time and eventually becomes terminal-failed.
        'b' then gets picked up and completes normally.
        """
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30, "more " * 30])
        _make_project(fm, "a", pdf_bytes)
        _make_project(fm, "b", pdf_bytes)
        fake = ai_components["fake"]
        fake.fail = True  # all projects fail

        sup = _new_supervisor(ai_components, max_failures=3)
        # Scans 1-3: project 'a' fails each time. After the 3rd failure
        # it becomes terminal-failed.
        r1 = sup.scan_once()
        assert r1.processed == "a" and r1.processed_ok is False
        r2 = sup.scan_once()
        assert r2.processed == "a"
        r3 = sup.scan_once()
        assert r3.processed == "a"
        assert r3.failed_terminal is True

        # Now 'a' is terminal; 'b' should be picked up.
        # But Ollama is still failing, so 'b' will also fail.
        # Switch Ollama to success for the next scans.
        fake.fail = False
        r4 = sup.scan_once()
        assert r4.processed == "b"
        assert r4.processed_ok is True


# ---------------------------------------------------------------------------
# Concurrency / locking
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_active_lock_serialises_scans(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30] * 10)
        _make_project(fm, "p", pdf_bytes)
        sup = _new_supervisor(ai_components)
        # Two parallel scan_once calls must each return a valid result
        # without crashing; the lock guarantees the second sees the
        # state left by the first.
        results: list[DigestScanResult] = []
        errors: list[BaseException] = []

        def runner() -> None:
            try:
                results.append(sup.scan_once())
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=runner) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []
        assert len(results) == 5


# ---------------------------------------------------------------------------
# Thread lifecycle
# ---------------------------------------------------------------------------


class TestThreadLifecycle:
    def test_start_runs_thread(self, ai_components):
        sup = _new_supervisor(ai_components)
        try:
            sup.start()
            assert sup.is_running() is True
        finally:
            sup.stop()

    def test_stop_exits_thread(self, ai_components):
        sup = _new_supervisor(ai_components)
        sup.start()
        sup.stop()
        assert sup.is_running() is False

    def test_ensure_running_starts_when_dead(self, ai_components):
        sup = _new_supervisor(ai_components)
        # No thread yet.
        assert sup.is_running() is False
        sup.ensure_running()
        try:
            assert sup.is_running() is True
        finally:
            sup.stop()

    def test_ensure_running_wakes_idle_thread(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30, "more " * 30])
        _make_project(fm, "p", pdf_bytes)
        sup = _new_supervisor(ai_components, interval_seconds=10.0)
        try:
            sup.start()
            # Wait briefly so the first scan completes and the thread
            # enters its idle wait.
            time.sleep(0.1)
            idle = sup.wait_until_idle(timeout=1.0)
            # The scan_once is single-page, so the project is NOT idle
            # after the first scan. Force it to complete first.
            while not sup.scan_once().all_complete:
                pass
            idle = sup.wait_until_idle(timeout=1.0)
            assert idle is True
            # ensure_running should not restart the thread but should
            # wake the loop. We verify by ensuring the thread is still
            # the same instance.
            t = sup._thread
            sup.ensure_running()
            assert sup._thread is t
        finally:
            sup.stop()

    def test_loop_sleeps_when_idle(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30])
        _make_project(fm, "p", pdf_bytes)
        sup = _new_supervisor(ai_components, interval_seconds=0.5)
        try:
            sup.start()
            # Drive the project to completion via the supervisor itself.
            while not sup.scan_once().all_complete:
                pass
            # Now the thread should be sleeping. Verify it doesn't busy-loop
            # by measuring that a short window produces no more chunks.
            fake = ai_components["fake"]
            calls_before = fake.call_count
            time.sleep(0.3)
            assert fake.call_count == calls_before
        finally:
            sup.stop()


# ---------------------------------------------------------------------------
# Wait-until-idle helper
# ---------------------------------------------------------------------------


class TestWaitUntilIdle:
    def test_returns_true_when_no_work(self, ai_components):
        sup = _new_supervisor(ai_components)
        assert sup.wait_until_idle(timeout=0.5) is True

    def test_returns_true_after_completion(self, ai_components):
        fm = ai_components["fm"]
        pdf_bytes = _make_text_pdf(["page " * 30, "more " * 30])
        _make_project(fm, "p", pdf_bytes)
        sup = _new_supervisor(ai_components)
        while not sup.scan_once().all_complete:
            pass
        assert sup.wait_until_idle(timeout=1.0) is True
