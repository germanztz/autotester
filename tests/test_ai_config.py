"""Tests for the IA section of app.models.config_manager.ConfigManager."""
from __future__ import annotations

import pytest

from app.models.config_manager import ConfigManager, IA_DEFAULTS


class TestIaDefaults:
    def test_defaults_contain_ia_block(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        cfg = mgr.load()
        assert "ia" in cfg
        ia = cfg["ia"]
        assert ia["ollama_url"] == "http://localhost:11434"
        assert ia["embedding_model"] == "qwen3-embedding:4b"
        assert ia["chunk_size"] == 500
        assert ia["chunk_overlap"] == 50

    def test_ia_defaults_constant_exports_expected_keys(self):
        assert set(IA_DEFAULTS.keys()) == {
            "ollama_url",
            "embedding_model",
            "chunk_size",
            "chunk_overlap",
        }


class TestIaUpdates:
    def test_update_ia_block(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_ia(ollama_url="http://example.com:11434", chunk_size=800)
        ia = mgr.load()["ia"]
        assert ia["ollama_url"] == "http://example.com:11434"
        assert ia["chunk_size"] == 800
        # untouched fields keep their defaults
        assert ia["embedding_model"] == "qwen3-embedding:4b"
        assert ia["chunk_overlap"] == 50

    def test_partial_update_preserves_other_ia_keys(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_ia(chunk_size=1024)
        mgr.update_ia(chunk_overlap=100)
        ia = mgr.load()["ia"]
        assert ia["chunk_size"] == 1024
        assert ia["chunk_overlap"] == 100

    def test_update_ia_rejects_unknown_key(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError):
            mgr.update_ia(some_unknown_field=1)

    @pytest.mark.parametrize("size", [0, -1])
    def test_update_ia_rejects_invalid_chunk_size(self, temp_workspace: dict, size: int):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError):
            mgr.update_ia(chunk_size=size)

    @pytest.mark.parametrize("overlap", [-1, 500, 999])
    def test_update_ia_rejects_invalid_chunk_overlap(self, temp_workspace: dict, overlap: int):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError):
            mgr.update_ia(chunk_overlap=overlap)

    def test_update_ia_persists_to_disk(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_ia(embedding_model="custom-model")
        import yaml

        on_disk = yaml.safe_load(temp_workspace["config"].read_text())
        assert on_disk["ia"]["embedding_model"] == "custom-model"

    def test_get_ia_returns_defaults_when_missing(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        cfg = mgr.load()
        cfg.pop("ia", None)
        mgr.save(cfg)
        # Re-load: defaults should be merged back
        ia = mgr.load()["ia"]
        assert ia["ollama_url"] == "http://localhost:11434"