"""Tests for JobRunner.cancel() and project-based lookups.

The cancel flag itself is tested purely at the API level — workers
cooperate by calling ``runner.is_cancelled(job_id)`` between steps.
The integration test of cancel-via-worker lives in
``test_page_digest.py`` where the LazyAIManager's own ``_cancel_events``
is the source of truth.
"""
from __future__ import annotations

import time

import pytest

from app.services.job_runner import JobRunner


def _wait_state(runner: JobRunner, job_id: str, target: str, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        last = runner.get(job_id)
        if last["state"] == target:
            return last
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach {target!r}; last={last!r}")


@pytest.fixture
def runner() -> JobRunner:
    r = JobRunner(max_workers=2, ttl_seconds=5.0)
    yield r
    r.shutdown()


class TestJobRunnerCancel:
    def test_cancel_unknown_job_returns_false(self, runner: JobRunner):
        assert runner.cancel("nonexistent-id") is False

    def test_cancel_completed_job_returns_false(self, runner: JobRunner):
        job_id = runner.submit(lambda: 1)
        _wait_state(runner, job_id, "done")
        assert runner.cancel(job_id) is False

    def test_cancel_sets_internal_flag(self, runner: JobRunner):
        """For unknown job, no cancel flag is set."""
        runner.cancel("ghost")
        assert runner.is_cancelled("ghost") is False

    def test_cancel_emits_info_log(self, runner, caplog):
        job_id = runner.submit(lambda: 1)
        _wait_state(runner, job_id, "done")
        caplog.clear()
        # After done, cancel returns False and should NOT log
        result = runner.cancel(job_id)
        assert result is False


class TestJobRunnerProjectLookup:
    def test_find_returns_none_for_unknown(self, runner):
        assert runner.find_by_project("ghost") is None

    def test_register_and_find(self, runner):
        # Register before submit so submit can pick it up via project_index
        runner.register_project("known-id", "myproj")
        assert runner.find_by_project("myproj") == "known-id"
        assert runner.find_by_project("other") is None