"""App-wide digest supervisor for autotester.

Runs at startup and then every ``interval_seconds`` (default 60) to walk
all projects and continue digesting any PDF that still has pending work.
Only one page is embedded at a time across the whole application.

Lifecycle:
    queued  --pickup-->  processing  --ok-->  queued (next page)
                                    --err--> error (consecutive_failures += 1)
    error   --pickup-->  processing ...
    processing <--consecutive_failures >= MAX_CONSECUTIVE_FAILURES--> failed (terminal)

The supervisor is a daemon thread owned by the Flask app. It exposes
``start()``, ``stop()`` and ``ensure_running()``. ``ensure_running()``
is called from the upload controller so a freshly uploaded PDF does not
have to wait the full poll interval before its first page is picked up.

The single-page-at-a-time property is enforced with an internal
``_active_lock`` so two pages can never be in flight concurrently even
if a stray caller invokes ``scan_once`` directly.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.services.digest_engine import LazyAIManager
from app.utils.logging_setup import get_logger

logger = get_logger()


@dataclass
class DigestScanResult:
    """Outcome of a single supervisor scan.

    Attributes:
        pending_count: Projects still needing digestion at scan start.
        processed: Project name whose page was attempted this scan, or None.
        processed_ok: True when a page was successfully embedded.
        error_message: Empty string on success; otherwise the error description.
        all_complete: True when no project needs work after the scan.
        failed_terminal: True when a project transitioned to terminal ``failed``.
    """

    pending_count: int = 0
    processed: Optional[str] = None
    processed_ok: bool = False
    error_message: str = ""
    all_complete: bool = False
    failed_terminal: bool = False


class DigestSupervisor:
    """Background thread that processes one PDF page at a time app-wide."""

    DEFAULT_INTERVAL_SECONDS = 60.0
    DEFAULT_LONG_INTERVAL_SECONDS = 600.0
    DEFAULT_MAX_CONSECUTIVE_FAILURES = 5
    DEFAULT_PER_PAGE_SLEEP_SECONDS = 0.05

    def __init__(
        self,
        lazy_ai_manager: LazyAIManager,
        file_manager: Any,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        long_interval_seconds: float = DEFAULT_LONG_INTERVAL_SECONDS,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        per_page_sleep_seconds: float = DEFAULT_PER_PAGE_SLEEP_SECONDS,
    ) -> None:
        self.lazy_ai_manager = lazy_ai_manager
        self.file_manager = file_manager
        self.interval_seconds = max(0.0, float(interval_seconds))
        self.long_interval_seconds = max(0.0, float(long_interval_seconds))
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))
        self.per_page_sleep_seconds = max(0.0, float(per_page_sleep_seconds))

        self._thread: Optional[threading.Thread] = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._active_lock = threading.Lock()
        self._started_lock = threading.Lock()
        # Pending change to flush via notify() — set when ensure_running wakes
        # the loop. Read once per scan iteration.

    # ----- thread control -------------------------------------------------

    def start(self) -> None:
        """Start the supervisor worker thread if it is not already running.

        Also kicks off an immediate scan by waking the event.
        """
        with self._started_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._wake.set()
            self._thread = threading.Thread(
                target=self._run_forever,
                name="digest-supervisor",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "Digest supervisor started (interval=%.1fs, long_interval=%.1fs, max_failures=%d)",
                self.interval_seconds,
                self.long_interval_seconds,
                self.max_consecutive_failures,
            )

    def stop(self) -> None:
        """Signal the worker to exit and wait for it to finish."""
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._started_lock:
            self._thread = None
        logger.info("Digest supervisor stopped")

    def ensure_running(self) -> None:
        """Make sure the supervisor thread is running and wake it.

        Called after a new project lands on disk (upload). If the thread
        is alive it just gets woken up; otherwise it is restarted.
        """
        if self._thread is None or not self._thread.is_alive():
            self.start()
        else:
            self._wake.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ----- main loop ------------------------------------------------------

    def _run_forever(self) -> None:
        """Worker body. Loops until ``stop()`` is called."""
        try:
            while not self._stop.is_set():
                # Reset the wake flag so a long sleep only ends early on
                # explicit wake from ensure_running() or stop().
                self._wake.clear()
                result = self.scan_once()
                if self._stop.is_set():
                    break
                if result.all_complete:
                    logger.info(
                        "All projects up to date. Switching scan interval to long_interval (%.1fs)",
                        self.long_interval_seconds,
                    )
                    # Idle: wait up to long_interval_seconds, but wake
                    # early if ensure_running() or stop() is called.
                    self._wake.wait(timeout=self.long_interval_seconds)
                # Otherwise loop immediately to process the next page.
                else:
                    if self.per_page_sleep_seconds > 0:
                        time.sleep(self.per_page_sleep_seconds)
                    self._wake.wait(timeout=0.0)
        except Exception as exc:  # noqa: BLE001
            logger.error("Digest supervisor worker crashed: %s: %s", type(exc).__name__, exc)

    # ----- single scan ----------------------------------------------------

    def scan_once(self) -> DigestScanResult:
        """Run a single scan over all projects, processing at most one page.

        Returns a ``DigestScanResult`` describing the outcome. Holds the
        ``_active_lock`` for the duration of the page embedding so two
        callers can never run pages concurrently.
        """
        result = DigestScanResult()
        with self._active_lock:
            projects = self._list_pending_projects()
            result.pending_count = len(projects)
            if not projects:
                # Nothing to do; scan is vacuously a success.
                result.all_complete = True
                result.processed_ok = True
                return result

            target = projects[0]
            result.processed = target
            outcome = self._process_one_project(target)
            result.processed_ok = outcome["ok"]
            result.error_message = outcome.get("error", "")
            result.failed_terminal = outcome.get("terminal_failed", False)

            # Recompute pending after the attempt.
            remaining = self._list_pending_projects()
            result.all_complete = len(remaining) == 0

            logger.debug(
                "Supervisor scan: project=%s ok=%s pending_after=%d all_complete=%s",
                target,
                outcome["ok"],
                len(remaining),
                result.all_complete,
            )
        return result

    # ----- internals ------------------------------------------------------

    def _list_pending_projects(self) -> list[str]:
        """Return the project names still needing digestion, sorted.

        Sorted alphabetically to give deterministic ordering across scans
        so the supervisor rotates fairly between projects.
        """
        pending: list[str] = []
        for entry in self.file_manager.list_projects():
            if self.lazy_ai_manager.needs_digest(entry.name):
                pending.append(entry.name)
        pending.sort()
        return pending

    def _process_one_project(self, project_name: str) -> dict[str, Any]:
        """Try to advance one page of ``project_name``.

        Returns a small dict:
            {"ok": bool, "error": str, "terminal_failed": bool}

        Errors and exceptions are caught here so the supervisor never
        crashes the worker loop.
        """
        state = self.lazy_ai_manager.project_status(project_name)
        # If the project was explicitly marked terminal, skip immediately.
        if state.get("state") == "failed":
            return {"ok": False, "error": state.get("error", ""), "terminal_failed": True}
        # Recover from a previous non-terminal failure so we can retry.
        if state.get("state") == "error":
            current_failures = int(state.get("consecutive_failures", 0))
            if current_failures >= self.max_consecutive_failures:
                self.lazy_ai_manager.mark_failed(
                    project_name,
                    f"Terminal failure after {current_failures} consecutive errors",
                )
                logger.error(
                    "Digest supervisor marked %s as failed after %d attempts",
                    project_name,
                    current_failures,
                )
                return {"ok": False, "error": "terminal failure", "terminal_failed": True}
            self.lazy_ai_manager.mark_unfailed(project_name)

        pdf_path = self.lazy_ai_manager.project_pdf_path(project_name)
        if pdf_path is None:
            reason = f"{type(FileNotFoundError).__name__}: PDF missing"
            self.lazy_ai_manager.mark_failed(project_name, reason)
            logger.warning(
                "Digest supervisor marked project as failed (no PDF): %s",
                project_name,
            )
            return {"ok": False, "error": reason, "terminal_failed": True}

        try:
            self.lazy_ai_manager.ensure_cache(project_name, pdf_path)
        except FileNotFoundError as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.lazy_ai_manager.mark_failed(project_name, reason)
            logger.warning(
                "Digest supervisor marked project as failed (cache): %s: %s",
                project_name,
                exc,
            )
            return {"ok": False, "error": reason, "terminal_failed": True}
        except Exception as exc:  # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Digest supervisor text extraction failed for %s: %s",
                project_name,
                reason,
            )
            self._bump_failure(project_name, reason)
            return {"ok": False, "error": reason, "terminal_failed": False}

        # Generate LLM title (non-fatal — log warning on failure, continue).
        if not self.lazy_ai_manager.project_status(project_name).get("title"):
            try:
                self.lazy_ai_manager.generate_title(project_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Title generation failed for %s (continuing): %s: %s",
                    project_name, type(exc).__name__, exc,
                )

        try:
            logger.info(
                "Starting semantic segmentation | Document: %s",
                project_name,
            )
            chunk_t0 = time.monotonic()
            info = self.lazy_ai_manager.process_one_chunk(project_name)
            chunk_elapsed = (time.monotonic() - chunk_t0) * 1000
            if info is not None:
                logger.info(
                    "Finished semantic segmentation | Document: %s | Chunk: %s/%s | Duration: %.0fms",
                    project_name, info.get("chunk"), info.get("total_chunks"), chunk_elapsed,
                )
        except Exception as exc:  # noqa: BLE001
            # process_one_page has already bumped consecutive_failures
            # and recorded the error. We only need to check whether the
            # threshold was reached.
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Digest supervisor page failed for %s: %s",
                project_name,
                reason,
            )
            terminal = self._maybe_mark_terminal(project_name, reason)
            return {"ok": False, "error": reason, "terminal_failed": terminal}

        if info is None:
            state_now = self.lazy_ai_manager.project_status(project_name)
            # If the project was explicitly marked terminal ("failed"),
            # respect that — do not override to "complete".
            if state_now.get("state") == "failed":
                logger.error(
                    "Digest supervisor: project %s is in terminal failed state",
                    project_name,
                )
                return {"ok": False, "error": state_now.get("error", ""), "terminal_failed": True}
            if state_now.get("state") != "complete":
                self.lazy_ai_manager._persist_state(  # type: ignore[attr-defined]
                    project_name,
                    state="complete",
                    consecutive_failures=0,
                )
            logger.info(
                "Digest supervisor completed project: %s", project_name
            )
            return {"ok": True, "error": "", "terminal_failed": False}

        return {"ok": True, "error": "", "terminal_failed": False}

    def _bump_failure(self, project_name: str, reason: str) -> bool:
        """Increment ``consecutive_failures`` and mark failed if at threshold.

        Returns ``True`` when the project was transitioned to terminal
        ``failed``. Used for errors that did NOT go through
        ``process_one_page`` (markdown extraction, etc.).
        """
        state = self.lazy_ai_manager.project_status(project_name)
        current = int(state.get("consecutive_failures", 0)) + 1
        return self._record_failure(project_name, current, reason)

    def _maybe_mark_terminal(self, project_name: str, reason: str) -> bool:
        """Check the current counter (already bumped by process_one_page).

        Returns ``True`` if the project crossed the terminal threshold.
        """
        state = self.lazy_ai_manager.project_status(project_name)
        current = int(state.get("consecutive_failures", 0))
        if current >= self.max_consecutive_failures:
            self.lazy_ai_manager.mark_failed(
                project_name,
                f"{reason} (after {current} attempts)",
            )
            logger.error(
                "Digest supervisor marked %s as failed after %d attempts: %s",
                project_name,
                current,
                reason,
            )
            return True
        return False

    def _record_failure(self, project_name: str, current: int, reason: str) -> bool:
        """Persist the bumped counter and mark terminal if at threshold."""
        if current >= self.max_consecutive_failures:
            self.lazy_ai_manager.mark_failed(
                project_name,
                f"{reason} (after {current} attempts)",
            )
            logger.error(
                "Digest supervisor marked %s as failed after %d attempts: %s",
                project_name,
                current,
                reason,
            )
            return True
        self.lazy_ai_manager._persist_state(  # type: ignore[attr-defined]
            project_name,
            consecutive_failures=current,
            error=reason,
            state="error",
        )
        return False

    # ----- test helper ----------------------------------------------------

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        """Block until the supervisor has no pending work or ``timeout`` elapses.

        Returns True if idle was reached, False on timeout. Only useful in
        tests — production code should not block on this.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._list_pending_projects():
                return True
            time.sleep(0.02)
        return False


