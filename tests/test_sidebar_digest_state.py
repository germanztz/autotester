"""Tests for FileManager.list_projects() reading digest.json sidecars."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.file_manager import FileManager


def _write_state(project_dir: Path, **fields) -> None:
    state = {
        "state": "queued",
        "total_words": 0,
        "total_chunks": 0,
        "chunks_processed": 0,
        "total_keywords": 0,
        "title": "",
        "language": "",
        "error": None,
        "updated_at": 0.0,
    }
    state.update(fields)
    (project_dir / "digest.json").write_text(json.dumps(state), encoding="utf-8")


class TestListProjectsWithDigestState:
    def test_new_project_returns_queued_state(self, temp_workspace):
        fm = FileManager(temp_workspace["projects"])
        proj = temp_workspace["projects"] / "fresh"
        proj.mkdir()
        (proj / "x.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

        entries = fm.list_projects()
        assert len(entries) == 1
        e = entries[0]
        assert e.name == "fresh"
        assert e.digest_state == "queued"
        assert e.digest_total_words == 0
        assert e.digest_total_chunks == 0
        assert e.digest_chunks_processed == 0
        assert e.digest_total_keywords == 0
        assert e.digest_error is None

    def test_project_with_processing_state(self, temp_workspace):
        fm = FileManager(temp_workspace["projects"])
        proj = temp_workspace["projects"] / "p"
        proj.mkdir()
        (proj / "x.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        _write_state(proj, state="processing", total_words=1000, total_chunks=5, chunks_processed=2, total_keywords=8)

        entries = fm.list_projects()
        assert entries[0].digest_state == "processing"
        assert entries[0].digest_total_words == 1000
        assert entries[0].digest_total_chunks == 5
        assert entries[0].digest_chunks_processed == 2
        assert entries[0].digest_total_keywords == 8

    def test_project_with_title_and_language(self, temp_workspace):
        fm = FileManager(temp_workspace["projects"])
        proj = temp_workspace["projects"] / "docs"
        proj.mkdir()
        (proj / "x.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        _write_state(proj, state="complete", title="My Document", language="es")

        entries = fm.list_projects()
        assert entries[0].digest_title == "My Document"
        assert entries[0].digest_language == "es"

    def test_project_with_complete_state(self, temp_workspace):
        fm = FileManager(temp_workspace["projects"])
        proj = temp_workspace["projects"] / "done"
        proj.mkdir()
        (proj / "x.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        _write_state(proj, state="complete", total_chunks=4, chunks_processed=4, total_keywords=12)

        entries = fm.list_projects()
        assert entries[0].digest_state == "complete"
        assert entries[0].digest_chunks_processed == 4
        assert entries[0].digest_total_keywords == 12

    def test_project_with_error_state(self, temp_workspace):
        fm = FileManager(temp_workspace["projects"])
        proj = temp_workspace["projects"] / "broken"
        proj.mkdir()
        (proj / "x.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        _write_state(proj, state="error", error="OllamaUnavailable: refused")

        entries = fm.list_projects()
        assert entries[0].digest_state == "error"
        assert "refused" in (entries[0].digest_error or "")

    def test_multiple_projects_sorted(self, temp_workspace):
        fm = FileManager(temp_workspace["projects"])
        for name in ("zeta", "alpha", "mu"):
            p = temp_workspace["projects"] / name
            p.mkdir()
            (p / "x.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
            _write_state(p, state="queued")

        names = [e.name for e in fm.list_projects()]
        assert names == ["alpha", "mu", "zeta"]

    def test_corrupt_digest_json_falls_back_to_queued(self, temp_workspace):
        fm = FileManager(temp_workspace["projects"])
        proj = temp_workspace["projects"] / "corrupt"
        proj.mkdir()
        (proj / "x.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        (proj / "digest.json").write_text("not json", encoding="utf-8")

        entries = fm.list_projects()
        assert entries[0].digest_state == "queued"