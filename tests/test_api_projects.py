"""Tests for the /ai/projects endpoint used by the sidebar poller."""
from __future__ import annotations

import io


class TestApiProjects:
    def test_returns_json_list(self, client):
        resp = client.get("/ai/projects", headers={"Accept": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "projects" in data
        assert isinstance(data["projects"], list)

    def test_empty_list_when_no_projects(self, client):
        resp = client.get("/ai/projects")
        data = resp.get_json()
        assert data["projects"] == []

    def test_includes_existing_projects(self, client, sample_pdf_bytes, temp_workspace):
        from app.models.file_manager import FileManager

        fm = FileManager(temp_workspace["projects"])
        fm.save_upload(io.BytesIO(sample_pdf_bytes), "x.pdf", "demo")

        resp = client.get("/ai/projects")
        data = resp.get_json()
        names = [p["name"] for p in data["projects"]]
        assert "demo" in names

    def test_each_project_has_digest_fields(self, client, sample_pdf_bytes):
        from app.models.file_manager import FileManager

        fm = client.application.extensions["file_manager"]
        fm.save_upload(io.BytesIO(sample_pdf_bytes), "x.pdf", "demo")

        resp = client.get("/ai/projects")
        data = resp.get_json()
        project = next(p for p in data["projects"] if p["name"] == "demo")
        for key in (
            "name",
            "pdf_count",
            "size_bytes",
            "digest_state",
            "digest_total_words",
            "digest_total_chunks",
            "digest_chunks_processed",
            "digest_total_keywords",
            "digest_error",
        ):
            assert key in project, f"missing key: {key}"

        assert project["digest_state"] == "queued"
        assert project["digest_total_chunks"] == 0

    def test_reflects_processing_state(self, client, sample_pdf_bytes):
        import json

        from app.models.file_manager import FileManager

        fm = client.application.extensions["file_manager"]
        entry = fm.save_upload(io.BytesIO(sample_pdf_bytes), "x.pdf", "digestme")
        proj_dir = fm.project_path(entry.name)
        (proj_dir / "digest.json").write_text(
            json.dumps(
                {
                    "state": "processing",
                    "total_words": 1000,
                    "total_chunks": 5,
                    "chunks_processed": 2,
                    "total_keywords": 8,
                    "error": None,
                    "updated_at": 0.0,
                }
            ),
            encoding="utf-8",
        )

        resp = client.get("/ai/projects")
        data = resp.get_json()
        proj = next(p for p in data["projects"] if p["name"] == "digestme")
        assert proj["digest_state"] == "processing"
        assert proj["digest_total_words"] == 1000
        assert proj["digest_total_chunks"] == 5