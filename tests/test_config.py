"""Tests for app.models.config_manager.ConfigManager."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.models.config_manager import ConfigManager, DEFAULT_CONFIG


class TestConfigManagerLoad:
    def test_loads_existing_config(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        cfg = mgr.load()
        assert cfg["theme"] == "system"
        assert cfg["app_name"] == "autotester"

    def test_creates_default_when_missing(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        mgr = ConfigManager(cfg_path)
        cfg = mgr.load()
        assert cfg == DEFAULT_CONFIG
        assert cfg_path.exists()

    def test_creates_default_when_empty(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("")
        mgr = ConfigManager(cfg_path)
        cfg = mgr.load()
        assert cfg["theme"] == DEFAULT_CONFIG["theme"]

    def test_merges_defaults_for_missing_keys(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump({"theme": "dark"}))
        mgr = ConfigManager(cfg_path)
        cfg = mgr.load()
        assert cfg["theme"] == "dark"
        assert "app_name" in cfg  # default preserved

    def test_handles_corrupt_yaml(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(":\ninvalid: : :")
        mgr = ConfigManager(cfg_path)
        cfg = mgr.load()
        assert cfg["theme"] == DEFAULT_CONFIG["theme"]


class TestConfigManagerSave:
    def test_persists_changes(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update(theme="dark")
        on_disk = yaml.safe_load(temp_workspace["config"].read_text())
        assert on_disk["theme"] == "dark"

    def test_update_preserves_other_keys(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        original_app_name = mgr.load()["app_name"]
        mgr.update(theme="light")
        assert mgr.load()["app_name"] == original_app_name

    def test_update_validates_theme(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError):
            mgr.update(theme="neon")

    def test_save_writes_yaml(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.save({"theme": "dark", "app_name": "autotester", "extra": 1})
        raw = yaml.safe_load(temp_workspace["config"].read_text())
        assert raw["extra"] == 1

    def test_get_returns_value_or_default(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        assert mgr.get("theme") == "system"
        assert mgr.get("missing", "fallback") == "fallback"


class TestConfigManagerValidThemes:
    @pytest.mark.parametrize("theme", ["light", "dark", "system"])
    def test_accepts_valid_themes(self, temp_workspace: dict, theme: str):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update(theme=theme)
        assert mgr.get("theme") == theme


class TestLoggingSection:
    def test_defaults_contain_logging_block(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        cfg = mgr.load()
        assert "logging" in cfg
        assert cfg["logging"]["level"] == "INFO"

    def test_update_logging_persists_level(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_logging(level="DEBUG")
        on_disk = yaml.safe_load(temp_workspace["config"].read_text())
        assert on_disk["logging"]["level"] == "DEBUG"

    def test_update_logging_rejects_invalid_level(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError):
            mgr.update_logging(level="NOPE")

    def test_update_logging_rejects_unknown_keys(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError):
            mgr.update_logging(unknown_field=1)

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_update_logging_accepts_valid_levels(
        self, temp_workspace: dict, level: str
    ):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_logging(level=level)
        assert mgr.load()["logging"]["level"] == level