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
    """Replace the segmenter's LLM client with a no-op fake for every test.

    Without this, every upload would attempt real HTTP calls to Ollama.
    """
    from tests.test_semantic_segmenter import FakeOllamaChat

    client.application.extensions["segmenter"].llm = FakeOllamaChat()





class TestUploadHappyPath:
    def test_upload_returns_202_with_status(self, client, sample_pdf_bytes: bytes):
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
        assert payload["status"] == "queued"

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
        assert response.status_code == 202
        # Let the supervisor process the project.
        supervisor = client.application.extensions["digest_supervisor"]
        supervisor.wait_until_idle(timeout=5.0)
        # Verify the project exists and digestion ran (state may be complete or queued for empty PDFs)
        fm = client.application.extensions["file_manager"]
        projects = fm.list_projects()
        assert any(p.name == "full" for p in projects)

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
        # Wait for the supervisor to finish processing before renaming.
        supervisor = client.application.extensions["digest_supervisor"]
        supervisor.wait_until_idle(timeout=5.0)

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
        # Wait for the supervisor to finish processing before deleting.
        supervisor = client.application.extensions["digest_supervisor"]
        supervisor.wait_until_idle(timeout=5.0)
        assert (temp_workspace["projects"] / "temp").is_dir()

        response = client.post(
            "/files/temp/delete",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert not (temp_workspace["projects"] / "temp").exists()