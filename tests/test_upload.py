"""End-to-end tests for PDF upload via the HTTP layer."""
from __future__ import annotations

import io

import pytest


class TestUploadHappyPath:
    def test_upload_creates_project_directory(
        self, client, sample_pdf_bytes: bytes, temp_workspace: dict
    ):
        data = {
            "project_name": "report",
            "pdf": (io.BytesIO(sample_pdf_bytes), "report.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert (temp_workspace["projects"] / "report").is_dir()

    def test_upload_persists_pdf_bytes(
        self, client, sample_pdf_bytes: bytes, temp_workspace: dict
    ):
        data = {
            "project_name": "doc",
            "pdf": (io.BytesIO(sample_pdf_bytes), "doc.pdf"),
        }
        client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        pdfs = list((temp_workspace["projects"] / "doc").glob("*.pdf"))
        assert pdfs
        assert pdfs[0].read_bytes() == sample_pdf_bytes

    def test_upload_with_special_chars_in_name_normalizes(
        self, client, sample_pdf_bytes: bytes, temp_workspace: dict
    ):
        data = {
            "project_name": "My Cool Report!",
            "pdf": (io.BytesIO(sample_pdf_bytes), "file.pdf"),
        }
        client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        assert (temp_workspace["projects"] / "mycoolreport").is_dir()


class TestUploadRejection:
    def test_upload_non_pdf_rejected(
        self, client, temp_workspace: dict
    ):
        data = {
            "project_name": "bad",
            "pdf": (io.BytesIO(b"this is plain text"), "fake.pdf"),
        }
        response = client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert not (temp_workspace["projects"] / "bad").exists()

    def test_upload_without_file_shows_error(self, client, temp_workspace: dict):
        response = client.post(
            "/files/upload",
            data={"project_name": "x"},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert not any(temp_workspace["projects"].iterdir())

    def test_upload_with_path_traversal_in_name_sanitizes(
        self, client, sample_pdf_bytes: bytes, temp_workspace: dict
    ):
        data = {
            "project_name": "../../etc/evil",
            "pdf": (io.BytesIO(sample_pdf_bytes), "f.pdf"),
        }
        client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        # The sanitized name "etcevil" should live inside projects/
        assert (temp_workspace["projects"] / "etcevil").is_dir()


class TestUploadThenRename:
    def test_upload_then_rename(
        self, client, sample_pdf_bytes: bytes, temp_workspace: dict
    ):
        data = {
            "project_name": "old",
            "pdf": (io.BytesIO(sample_pdf_bytes), "f.pdf"),
        }
        client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        response = client.post(
            "/files/old/rename",
            data={"new_name": "new"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert not (temp_workspace["projects"] / "old").exists()
        assert (temp_workspace["projects"] / "new").is_dir()


class TestUploadThenDelete:
    def test_upload_then_delete(
        self, client, sample_pdf_bytes: bytes, temp_workspace: dict
    ):
        data = {
            "project_name": "temp",
            "pdf": (io.BytesIO(sample_pdf_bytes), "f.pdf"),
        }
        client.post(
            "/files/upload",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert (temp_workspace["projects"] / "temp").is_dir()

        response = client.post(
            "/files/temp/delete",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert not (temp_workspace["projects"] / "temp").exists()