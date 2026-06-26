"""Tests for app.services.job_runner.JobRunner."""
from __future__ import annotations

import time

import pytest

from app.services.job_runner import JobRunner


def _wait_for_state(runner: JobRunner, job_id: str, target: str, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = runner.get(job_id)
        if last["state"] == target:
            return last
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach {target!r}; last={last!r}")


@pytest.fixture
def runner() -> JobRunner:
    r = JobRunner(max_workers=2, ttl_seconds=1.0)
    yield r
    r.shutdown()


def test_submit_returns_job_id(runner):
    job_id = runner.submit(lambda: "ok")
    assert isinstance(job_id, str)
    assert len(job_id) >= 8


def test_completed_job_reports_done_with_result(runner):
    job_id = runner.submit(lambda: 42)
    status = _wait_for_state(runner, job_id, "done")
    assert status["result"] == 42
    assert status["error"] is None
    assert status["elapsed"] >= 0


def test_failed_job_reports_error(runner):
    def boom():
        raise ValueError("nope")

    job_id = runner.submit(boom)
    status = _wait_for_state(runner, job_id, "error")
    assert "ValueError" in status["error"]
    assert "nope" in status["error"]


def test_running_job_has_elapsed_increasing(runner):
    def slow():
        time.sleep(0.1)
        return "ok"

    job_id = runner.submit(slow)
    time.sleep(0.05)
    status = runner.get(job_id)
    assert status["state"] in ("running", "done")
    if status["state"] == "running":
        assert status["elapsed"] > 0


def test_unknown_job_reports_unknown_state(runner):
    status = runner.get("nonexistent-id")
    assert status["state"] == "unknown"
    assert "not found" in status["error"]


def test_result_with_to_dict_is_serialized(runner):
    class Obj:
        def __init__(self, v):
            self.v = v

        def to_dict(self):
            return {"value": self.v}

    job_id = runner.submit(lambda: Obj(7))
    status = _wait_for_state(runner, job_id, "done")
    assert status["result"] == {"value": 7}


def test_cleanup_removes_old_finished_jobs(runner):
    job_id = runner.submit(lambda: 1)
    _wait_for_state(runner, job_id, "done")
    time.sleep(1.1)
    removed = runner.cleanup()
    assert removed == 1
    assert runner.get(job_id)["state"] == "unknown"


def test_cleanup_keeps_recent_jobs(runner):
    job_id = runner.submit(lambda: 1)
    _wait_for_state(runner, job_id, "done")
    removed = runner.cleanup()
    assert removed == 0
    assert runner.get(job_id)["state"] == "done"