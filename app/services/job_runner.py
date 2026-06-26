"""In-process async job runner.

Single-process ThreadPoolExecutor with a thread-safe job registry. The
runner is intentionally simple: no persistence, no retries. Completed jobs
linger for ``ttl_seconds`` so that the final status poll from the client
can still succeed, then are evicted.

Job state shape:
    {
        "state": "pending" | "running" | "done" | "error",
        "started_at": float | None,    # monotonic seconds
        "finished_at": float | None,
        "elapsed": float,              # updated on get()
        "result": Any | None,          # callable return value
        "error": str | None,
    }
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock
from typing import Any, Callable, Optional

from app.utils.logging_setup import get_logger

logger = get_logger()


class JobRunner:
    """Run callables asynchronously and report their status."""

    def __init__(self, max_workers: int = 2, ttl_seconds: float = 60.0) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ai-job")
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, Event] = {}
        self._project_index: dict[str, str] = {}  # project_name -> job_id
        self._lock = Lock()
        self.ttl_seconds = ttl_seconds

    def is_cancelled(self, job_id: str) -> bool:
        """Return True if ``cancel(job_id)`` has been called for this job."""
        with self._lock:
            event = self._cancel_events.get(job_id)
            return event is not None and event.is_set()

    def _cancel_events_for(self, job_id: str) -> Event:
        """Return the cancel Event for a job.

        Workers may call this to obtain the Event and pass it to subroutines
        for cooperative cancellation. Returns a never-set Event for unknown
        jobs so calling code doesn't need to handle None.
        """
        with self._lock:
            return self._cancel_events.setdefault(job_id, Event())

    def cancel(self, job_id: str) -> bool:
        """Signal a running job to stop at the next checkpoint.

        Returns True if a cancel flag was set (or was already set) on a
        known job; False if the job is unknown or already finished.
        """
        with self._lock:
            if job_id not in self._jobs:
                return False
            job = self._jobs[job_id]
            if job["state"] in ("done", "error"):
                return False
            event = self._cancel_events.setdefault(job_id, Event())
            event.set()
            logger.info("Job %s cancellation requested", job_id)
            return True

    def register_project(self, job_id: str, project_name: str) -> None:
        """Associate ``project_name`` with ``job_id`` for lookup."""
        with self._lock:
            self._project_index[project_name] = job_id

    def find_by_project(self, project_name: str) -> Optional[str]:
        """Return the job_id associated with ``project_name`` or None."""
        with self._lock:
            return self._project_index.get(project_name)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        """Submit a callable. Returns a job_id used to poll status.

        The callable may cooperate with ``cancel(job_id)`` by calling
        ``runner.is_cancelled(job_id)`` between steps. The runner exposes
        the cancel event for the current job so a worker can pass the
        event into its own subroutines.
        """
        job_id = uuid.uuid4().hex
        fn_name = getattr(fn, "__name__", repr(fn))
        logger.info("Job %s submitted: %s", job_id, fn_name)
        with self._lock:
            self._jobs[job_id] = {
                "state": "pending",
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }
            event = self._cancel_events.setdefault(job_id, Event())

        # Bind job_id into the worker closure by passing the event explicitly
        # to the user callable. If the user wants cooperative cancellation,
        # they can check ``runner.is_cancelled(job_id)`` themselves.
        def _runner() -> None:
            with self._lock:
                self._jobs[job_id]["state"] = "running"
                self._jobs[job_id]["started_at"] = time.monotonic()
            logger.debug("Job %s state -> running (%s)", job_id, fn_name)
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - we deliberately capture all
                with self._lock:
                    self._jobs[job_id]["state"] = "error"
                    self._jobs[job_id]["error"] = f"{type(exc).__name__}: {exc}"
                    self._jobs[job_id]["finished_at"] = time.monotonic()
                logger.error("Job %s failed: %s: %s", job_id, type(exc).__name__, exc)
                return
            with self._lock:
                self._jobs[job_id]["state"] = "done"
                self._jobs[job_id]["result"] = result
                self._jobs[job_id]["finished_at"] = time.monotonic()
            logger.debug("Job %s state -> done", job_id)

        future: Future = self._executor.submit(_runner)
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        return job_id

    def get(self, job_id: str) -> dict[str, Any]:
        """Return a JSON-serializable status snapshot for the job.

        Unknown ids return ``{"state": "unknown", "error": "..."}``.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"state": "unknown", "error": "job not found"}

            now = time.monotonic()
            started = job["started_at"]
            finished = job["finished_at"]
            if finished is not None:
                elapsed = max(0.0, finished - (started or finished))
            elif started is not None:
                elapsed = max(0.0, now - started)
            else:
                elapsed = 0.0

            snapshot = {
                "state": job["state"],
                "elapsed": round(elapsed, 2),
                "result": job["result"].to_dict() if hasattr(job["result"], "to_dict") else job["result"],
                "error": job["error"],
            }
            return snapshot

    def cleanup(self) -> int:
        """Remove finished jobs older than ttl_seconds. Returns count removed."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            stale = []
            for job_id, job in self._jobs.items():
                finished = job["finished_at"]
                if finished is None:
                    continue
                if (now - finished) > self.ttl_seconds:
                    stale.append(job_id)
            for job_id in stale:
                del self._jobs[job_id]
                self._cancel_events.pop(job_id, None)
                # Remove project_index entries pointing at the stale job.
                stale_projects = [p for p, j in self._project_index.items() if j == job_id]
                for p in stale_projects:
                    del self._project_index[p]
                removed += 1
        return removed

    def shutdown(self, wait: bool = True) -> None:
        """Stop the executor. Called on app teardown / test fixtures."""
        self._executor.shutdown(wait=wait)