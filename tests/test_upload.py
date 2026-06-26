"""End-to-end tests for PDF upload via the HTTP layer.

The upload flow is now async: the controller returns 202 with a job_id and
the AI digest runs in a background thread. These tests cover both the
synchronous (browser form submit) and JSON request paths.
"""
from __future__ import annotations

import io
import time

import pytest


@pytest.fixture(autouse=True)
def _patch_ollama(client):
    """Replace the AI manager's Ollama client with a no-op fake for every test.

    Without this, every upload would attempt real HTTP calls to Ollama.
    """
    from test_ai_manager import FakeOllama

    client.application.extensions["ai_manager"].ollama = FakeOllama()


def _wait_done(client, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = client.get(f"/ai/status/{job_id}").get_json()
        if last.get("state") in ("done", "error"):
            return last
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} never finished: {last}")


def _wait_done_for_project(client, project: str, timeout: float = 5.0) -> dict:
    """Poll all jobs (looking up the latest one for the project)."""
    deadline = time.monotonic() + timeout
    runner = client.application.extensions["job_runner"]
    while time.monotonic() < deadline:
        for jid in list(runner._jobs.keys()):
            snap = runner.get(jid)
            if snap.get("state") == "done" and snap.get("result", {}).get("project_name") == project:
                return snap
        time.sleep(0.05)
    raise AssertionError(f"No done job found for project {project}")


class TestUploadHappyPath:
    def test_upload_returns_202_with_job_id(self, client, sample_pdf_bytes: bytes):
        data = {
            "project_name": "report",
            "pdf": (io.BytesIO(sample_pdf_bytes), "report.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 202
        payload = response.get_json()
        assert payload["project"] == "report"
        assert "job_id" in payload

    def test_upload_creates_project_directory(
        self, client, sample_pdf_bytes: bytes, temp_workspace: dict
    ):
        data = {
            "project_name": "doc",
            "pdf": (io.BytesIO(sample_pdf_bytes), "doc.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 202
        assert (temp_workspace["projects"] / "doc").is_dir()

    def test_upload_then_digest_completes(
        self, client, sample_pdf_bytes: bytes
    ):
        data = {
            "project_name": "full",
            "pdf": (io.BytesIO(sample_pdf_bytes), "doc.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        job_id = response.get_json()["job_id"]
        final = _wait_done(client, job_id)
        assert final["state"] == "done"
        # The minimal conftest PDF has empty extractable text, so chunks == 0.
        # The important thing is the job completed without error.
        assert final["result"]["project_name"] == "full"

    def test_upload_classic_form_redirects(self, client, sample_pdf_bytes: bytes):
        data = {
            "project_name": "browser",
            "pdf": (io.BytesIO(sample_pdf_bytes), "doc.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert response.status_code == 302


class TestUploadRejection:
    def test_upload_non_pdf_rejected_with_400(self, client):
        data = {
            "project_name": "bad",
            "pdf": (io.BytesIO(b"this is plain text"), "fake.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_upload_without_file_returns_400(self, client):
        response = client.post(
            "/files/upload",
            data={"project_name": "x"},
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400

    def test_upload_with_path_traversal_in_name_sanitizes(
        self, client, sample_pdf_bytes: bytes, temp_workspace: dict
    ):
        data = {
            "project_name": "../../etc/evil",
            "pdf": (io.BytesIO(sample_pdf_bytes), "f.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 202
        # Sanitized name is "etcevil"
        assert (temp_workspace["projects"] / "etcevil").is_dir()


class TestUploadThenRename:
    def test_upload_then_rename(self, client, sample_pdf_bytes: bytes, temp_workspace: dict):
        data = {
            "project_name": "old",
            "pdf": (io.BytesIO(sample_pdf_bytes), "f.pdf"),
        }
        client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        # Wait for the lazy digest to finish so the rename is unambiguous.
        runner = client.application.extensions["job_runner"]
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            job_id = runner.find_by_project("old")
            if job_id is None:
                break
            snap = runner.get(job_id)
            if snap["state"] in ("done", "error"):
                break
            time.sleep(0.02)

        response = client.post(
            "/files/old/rename",
            data={"new_name": "new"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert not (temp_workspace["projects"] / "old").exists()
        assert (temp_workspace["projects"] / "new").is_dir()


class TestUploadThenDelete:
    def test_upload_then_delete(self, client, sample_pdf_bytes: bytes, temp_workspace: dict):
        data = {
            "project_name": "temp",
            "pdf": (io.BytesIO(sample_pdf_bytes), "f.pdf"),
        }
        client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        # Wait for the lazy digest to finish so the delete is unambiguous.
        runner = client.application.extensions["job_runner"]
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            job_id = runner.find_by_project("temp")
            if job_id is None:
                break
            snap = runner.get(job_id)
            if snap["state"] in ("done", "error"):
                break
            time.sleep(0.02)
        assert (temp_workspace["projects"] / "temp").is_dir()

        response = client.post(
            "/files/temp/delete",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert not (temp_workspace["projects"] / "temp").exists()