"""Tests for the game configuration section (app.models.config_manager)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.models.config_manager import (
    ConfigManager,
    GAME_DEFAULTS,
    DEFAULT_CONFIG,
)


class TestGameDefaults:
    def test_defaults_contain_game_block(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        cfg = mgr.load()
        assert "game" in cfg
        assert cfg["game"]["language"] == "es"
        assert cfg["game"]["questions_per_paragraph"] == 5
        assert cfg["game"]["correct_to_master"] == 3
        assert cfg["game"]["model"] == "qwen3.5:latest"

    def test_game_defaults_constant_exports_expected_keys(self):
        assert set(GAME_DEFAULTS) == {
            "language",
            "questions_per_paragraph",
            "correct_to_master",
            "model",
        }

    def test_default_config_includes_game(self):
        assert "game" in DEFAULT_CONFIG
        assert DEFAULT_CONFIG["game"] == GAME_DEFAULTS


class TestGameUpdates:
    def test_update_game_block(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_game(language="en", questions_per_paragraph=3)
        cfg = mgr.load()
        assert cfg["game"]["language"] == "en"
        assert cfg["game"]["questions_per_paragraph"] == 3
        assert cfg["game"]["correct_to_master"] == 3  # unchanged default

    def test_partial_update_preserves_other_game_keys(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_game(language="fr")
        cfg = mgr.load()
        assert cfg["game"]["language"] == "fr"
        assert cfg["game"]["questions_per_paragraph"] == 5  # default preserved
        assert cfg["game"]["correct_to_master"] == 3

    def test_update_game_rejects_unknown_key(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError, match="Unknown game keys"):
            mgr.update_game(unknown_field=1)

    def test_update_game_rejects_empty_language(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError, match="game.language"):
            mgr.update_game(language="")

    def test_update_game_rejects_zero_questions(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError, match="questions_per_paragraph"):
            mgr.update_game(questions_per_paragraph=0)

    def test_update_game_rejects_zero_correct_to_master(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        with pytest.raises(ValueError, match="correct_to_master"):
            mgr.update_game(correct_to_master=0)

    def test_update_game_persists_to_disk(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_game(language="de")
        on_disk = yaml.safe_load(temp_workspace["config"].read_text())
        assert on_disk["game"]["language"] == "de"

    def test_get_game_returns_defaults_when_missing(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump({"theme": "dark"}))
        mgr = ConfigManager(cfg_path)
        cfg = mgr.load()
        assert cfg["game"]["language"] == "es"
        assert cfg["game"]["questions_per_paragraph"] == 5
        assert cfg["game"]["correct_to_master"] == 3
