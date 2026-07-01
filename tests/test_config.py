"""Tests for app.models.config_manager.ConfigManager."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.models.config_manager import (
    ConfigManager,
    DEFAULT_CONFIG,
    IA_DEFAULTS,
    _validate_ia,
)


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


class TestIAQuestionTrueFalsePrompt:
    def test_default_contains_true_false_prompt(self):
        assert "question_true_false_user_prompt_tpl" in IA_DEFAULTS
        tpl = IA_DEFAULTS["question_true_false_user_prompt_tpl"]
        assert "{text}" in tpl
        assert "{keyword}" in tpl
        assert "{target_response}" in tpl
        assert "{language}" in tpl

    def test_validate_ia_rejects_empty_true_false_prompt(self):
        with pytest.raises(ValueError, match="question_true_false_user_prompt_tpl"):
            _validate_ia({
                "ollama_url": "http://dummy-server",
                "ollama_model": "dummy-model",
                "chunk_size": 100,
                "chunk_overlap": 10,
                "system_prompt": "a",
                "user_prompt_tpl": "a {text}",
                "title_user_prompt_tpl": "a {text}",
                "question_true_false_user_prompt_tpl": "",
            })

    def test_validate_ia_rejects_missing_text_placeholder(self):
        with pytest.raises(ValueError, match=r"question_true_false.*{text}"):
            _validate_ia({
                "ollama_url": "http://dummy-server",
                "ollama_model": "dummy-model",
                "chunk_size": 100,
                "chunk_overlap": 10,
                "system_prompt": "a",
                "user_prompt_tpl": "a {text}",
                "title_user_prompt_tpl": "a {text}",
                "question_true_false_user_prompt_tpl": "no placeholder {keyword} {target_response} {language}",
            })

    def test_validate_ia_accepts_valid_true_false_prompt(self):
        _validate_ia({
            "ollama_url": "http://dummy-server",
            "ollama_model": "dummy-model",
            "chunk_size": 100,
            "chunk_overlap": 10,
            "system_prompt": "a",
            "user_prompt_tpl": "a {text}",
            "title_user_prompt_tpl": "a {text}",
            "question_true_false_user_prompt_tpl": "valid {text} {keyword} {target_response} {language}",
        })

    def test_update_ia_persists_true_false_prompt(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update_ia(question_true_false_user_prompt_tpl="custom {text} {keyword} {target_response} {language}")
        cfg = mgr.load()
        assert cfg["ia"]["question_true_false_user_prompt_tpl"] == "custom {text} {keyword} {target_response} {language}"

    def test_config_route_saves_true_false_prompt(self, client):
        resp = client.post("/config/", data={
            "theme": "system",
            "ollama_url": "http://dummy-server",
            "ollama_model": "dummy-model",
            "chunk_size": 100,
            "chunk_overlap": 10,
            "system_prompt": "sp",
            "user_prompt_tpl": "up {text}",
            "title_user_prompt_tpl": "tup {text}",
            "question_true_false_user_prompt_tpl": "tf {text} {keyword} {target_response} {language}",
            "log_level": "INFO",
        }, follow_redirects=True)
        assert resp.status_code == 200


class TestConfigManagerReset:
    def test_reset_restores_defaults(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update(theme="dark")
        mgr.update_ia(chunk_size=999, chunk_overlap=100)
        mgr.update_logging(level="DEBUG")
        mgr.update_game(language="fr", questions_per_paragraph=2)
        mgr.reset()
        cfg = mgr.load()
        assert cfg["theme"] == DEFAULT_CONFIG["theme"]
        assert cfg["ia"]["chunk_size"] == DEFAULT_CONFIG["ia"]["chunk_size"]
        assert cfg["logging"]["level"] == DEFAULT_CONFIG["logging"]["level"]
        assert cfg["game"]["language"] == DEFAULT_CONFIG["game"]["language"]

    def test_reset_preserves_app_name(self, temp_workspace: dict):
        mgr = ConfigManager(temp_workspace["config"])
        mgr.update(theme="light")
        orig_name = mgr.load()["app_name"]
        mgr.reset()
        assert mgr.load()["app_name"] == orig_name


class TestResetRoute:
    def test_reset_via_post_redirects(self, client):
        resp = client.post("/config/reset")
        assert resp.status_code == 302
        assert resp.location.endswith("/config/")

    def test_reset_restores_defaults_on_disk(self, client, app):
        cm = app.extensions["config_manager"]
        cm.update(theme="dark")
        cm.update_ia(chunk_size=999)
        client.post("/config/reset")
        cfg = cm.load()
        assert cfg["theme"] == DEFAULT_CONFIG["theme"]
        assert cfg["ia"]["chunk_size"] == DEFAULT_CONFIG["ia"]["chunk_size"]

    def test_reset_returns_success_flash(self, client):
        resp = client.post("/config/reset", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Settings reset to defaults" in resp.data