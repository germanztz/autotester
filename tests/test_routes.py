"""Tests for the Flask routes (GET/POST endpoints and view rendering)."""
from __future__ import annotations

import io

import pytest


class TestMainRoute:
    def test_index_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_index_renders_title(self, client):
        response = client.get("/")
        assert b"autotester" in response.data

    def test_index_includes_sidebar(self, client):
        response = client.get("/")
        assert b"Projects" in response.data


class TestConfigRoute:
    def test_get_config_returns_200(self, client):
        response = client.get("/config/")
        assert response.status_code == 200

    def test_get_config_shows_theme_options(self, client):
        response = client.get("/config/")
        for theme in (b"light", b"dark", b"system"):
            assert theme in response.data

    def test_post_theme_dark_persists(self, client, temp_workspace: dict):
        response = client.post("/config/", data={"theme": "dark"}, follow_redirects=True)
        assert response.status_code == 200
        assert temp_workspace["config"].read_text().find("dark") >= 0

    def test_post_theme_light_persists(self, client, temp_workspace: dict):
        client.post("/config/", data={"theme": "light"})
        assert "light" in temp_workspace["config"].read_text()

    def test_post_invalid_theme_returns_400_or_redirects(self, client):
        response = client.post("/config/", data={"theme": "neon"})
        assert response.status_code in (302, 400)


class TestFilesRoute:
    def test_upload_route_exists(self, client):
        response = client.post(
            "/files/upload",
            data={"project_name": "demo"},
            content_type="multipart/form-data",
        )
        # Should at least redirect or respond (no file => flash + redirect)
        assert response.status_code in (302, 400)

    def test_delete_nonexistent_returns_redirect_or_404(self, client):
        response = client.post("/files/ghost/delete")
        assert response.status_code in (302, 404)

    def test_rename_nonexistent_redirects(self, client):
        response = client.post(
            "/files/ghost/rename",
            data={"new_name": "new"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"not found" in response.data.lower() or b"ghost" in response.data

    def test_index_lists_existing_projects(self, client, sample_pdf_bytes: bytes, temp_workspace: dict):
        from app.models.file_manager import FileManager

        fm = FileManager(temp_workspace["projects"])
        fm.save_upload(io.BytesIO(sample_pdf_bytes), "f.pdf", "myproj")

        response = client.get("/")
        assert response.status_code == 200
        assert b"myproj" in response.data