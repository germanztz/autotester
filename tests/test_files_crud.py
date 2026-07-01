"""Tests for app.models.file_manager.FileManager (CRUD on PDF projects)."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.models.file_manager import FileManager, ProjectEntry


class TestFileManagerList:
    def test_empty_when_no_projects(self, temp_workspace: dict):
        mgr = FileManager(temp_workspace["projects"])
        assert mgr.list_projects() == []

    def test_lists_existing_projects(self, temp_workspace: dict, sample_pdf_bytes: bytes):
        proj = temp_workspace["projects"] / "report"
        proj.mkdir()
        (proj / "doc.pdf").write_bytes(sample_pdf_bytes)

        mgr = FileManager(temp_workspace["projects"])
        entries = mgr.list_projects()

        assert len(entries) == 1
        assert entries[0].name == "report"
        assert entries[0].pdf_count == 1
        assert entries[0].size_bytes == len(sample_pdf_bytes)

    def test_ignores_orphan_files(self, temp_workspace: dict, sample_pdf_bytes: bytes):
        (temp_workspace["projects"] / "loose.pdf").write_bytes(sample_pdf_bytes)
        mgr = FileManager(temp_workspace["projects"])
        assert mgr.list_projects() == []


class TestFileManagerSave:
    def test_save_creates_project_directory(
        self, temp_workspace: dict, sample_pdf_bytes: bytes
    ):
        mgr = FileManager(temp_workspace["projects"])
        entry = mgr.save_upload(
            fileobj=io.BytesIO(sample_pdf_bytes),
            original_filename="My Report.pdf",
            project_name="my-report",
        )

        target = temp_workspace["projects"] / "my-report"
        assert target.is_dir()
        assert entry.name == "my-report"
        assert entry.pdf_count == 1
        assert (target / "My Report.pdf").exists() or any(target.glob("*.pdf"))

    def test_save_rejects_invalid_pdf(self, temp_workspace: dict):
        mgr = FileManager(temp_workspace["projects"])
        with pytest.raises(ValueError):
            mgr.save_upload(
                fileobj=io.BytesIO(b"not a pdf"),
                original_filename="bad.pdf",
                project_name="bad",
            )

    def test_save_appends_collision_suffix(self, temp_workspace: dict, sample_pdf_bytes: bytes):
        mgr = FileManager(temp_workspace["projects"])
        mgr.save_upload(io.BytesIO(sample_pdf_bytes), "a.pdf", "doc")
        mgr.save_upload(io.BytesIO(sample_pdf_bytes), "a.pdf", "doc")

        names = sorted(p.name for p in (temp_workspace["projects"]).iterdir())
        assert names == ["doc", "doc_2"]


class TestFileManagerRename:
    def test_renames_project_directory(self, temp_workspace: dict, sample_pdf_bytes: bytes):
        mgr = FileManager(temp_workspace["projects"])
        mgr.save_upload(io.BytesIO(sample_pdf_bytes), "f.pdf", "old_name")

        mgr.rename_project("old_name", "new_name")

        assert not (temp_workspace["projects"] / "old_name").exists()
        assert (temp_workspace["projects"] / "new_name").is_dir()

    def test_rename_to_existing_appends_suffix(
        self, temp_workspace: dict, sample_pdf_bytes: bytes
    ):
        mgr = FileManager(temp_workspace["projects"])
        mgr.save_upload(io.BytesIO(sample_pdf_bytes), "f.pdf", "a")
        mgr.save_upload(io.BytesIO(sample_pdf_bytes), "g.pdf", "b")

        mgr.rename_project("a", "b")

        assert (temp_workspace["projects"] / "b").is_dir()
        assert (temp_workspace["projects"] / "b_2").is_dir()

    def test_rename_missing_raises(self, temp_workspace: dict):
        mgr = FileManager(temp_workspace["projects"])
        with pytest.raises(FileNotFoundError):
            mgr.rename_project("ghost", "new")

    def test_rename_invalid_name_raises(self, temp_workspace: dict, sample_pdf_bytes: bytes):
        mgr = FileManager(temp_workspace["projects"])
        mgr.save_upload(io.BytesIO(sample_pdf_bytes), "f.pdf", "real")
        with pytest.raises(ValueError):
            mgr.rename_project("real", "../escape")


class TestFileManagerDelete:
    def test_delete_removes_directory(self, temp_workspace: dict, sample_pdf_bytes: bytes):
        mgr = FileManager(temp_workspace["projects"])
        mgr.save_upload(io.BytesIO(sample_pdf_bytes), "f.pdf", "doomed")

        mgr.delete_project("doomed")

        assert not (temp_workspace["projects"] / "doomed").exists()

    def test_delete_missing_raises(self, temp_workspace: dict):
        mgr = FileManager(temp_workspace["projects"])
        with pytest.raises(FileNotFoundError):
            mgr.delete_project("ghost")

    def test_delete_invalid_name_raises(self, temp_workspace: dict):
        mgr = FileManager(temp_workspace["projects"])
        with pytest.raises(ValueError):
            mgr.delete_project("../escape")


class TestProjectEntry:
    def test_to_dict_serializable(self):
        entry = ProjectEntry(name="x", pdf_count=2, size_bytes=1024, created_at=1700000000.0)
        d = entry.to_dict()
        assert d["name"] == "x"
        assert d["pdf_count"] == 2
        assert d["size_bytes"] == 1024
        assert isinstance(d["created_at"], float)
        assert d["digest_reading_check"] == 0
        assert d["digest_fill_gap"] == 0
        assert d["digest_true_false"] == 0