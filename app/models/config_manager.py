"""Configuration manager for autotester.

Loads and persists user-facing settings (theme, app options) in YAML.
Falls back to defaults when the file is missing, empty or corrupt.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from app.utils.logging_setup import VALID_LOG_LEVELS


VALID_THEMES = ("light", "dark", "system")

_DEFAULT_SYSTEM_PROMPT = (
    'You are a precise document analyst.\n'
    'Analyze the provided text, understand its content and structure.\n'
    'Return ONLY valid JSON (no markdown, no extra text).\n'
)

_DEFAULT_USER_PROMPT_TPL = (
    'Based on the following text, extract 1 to 10 keywords that represent the main topics.\n'
    'Text:\n'
    '{text}\n\n'
    'Return ONLY valid JSON conforming to this schema:\n'
    '{{"text_keywords": ["kw1", "kw2", ...]}}\n'
    'If no meaningful keywords can be extracted, return:\n'
    '{{"text_keywords": []}}'
)

_DEFAULT_QUESTION_TRUE_FALSE_USER_PROMPT_TPL = (
    'Based on the following text, Generate a true/false statement in language "{language}".\n'
    'The statement must target the keyword "{keyword}".\n'
    'The correct answer must be "{target_response}".\n'
    'Do NOT copy phrases from the original text - rephrase the concept in your own words.\n'
    'Text:\n'
    '{text}\n\n'
    'Return ONLY valid JSON conforming to this schema:\n'
    '{{"type": "true_false", "question": "your rephrased statement here", "correct_answer": "{target_response}"}}'
)

_DEFAULT_TITLE_USER_PROMPT_TPL = (
    'Based on the following text, generate a short title of 1 to 7 words.\n'
    'that represents the main subject of the text, use expressive emojis; \n'
    'also, detect the language of the text.\n'
    'Text:\n'
    '{text}\n\n'
    'Return ONLY valid JSON conforming to this schema:\n'
    '{{"title": "short descriptive title with emojis", "language": "ISO 639-1 code (e.g., en, es, fr, de, pt, it)"}}'
)

_PROMPT_KEYS = [
    "system_prompt",
    "user_prompt_tpl",
    "title_user_prompt_tpl",
    "question_true_false_user_prompt_tpl",
]

_PROMPT_DEFAULTS: dict[str, str] = {
    "system_prompt": _DEFAULT_SYSTEM_PROMPT,
    "user_prompt_tpl": _DEFAULT_USER_PROMPT_TPL,
    "title_user_prompt_tpl": _DEFAULT_TITLE_USER_PROMPT_TPL,
    "question_true_false_user_prompt_tpl": _DEFAULT_QUESTION_TRUE_FALSE_USER_PROMPT_TPL,
}

IA_DEFAULTS: dict[str, Any] = {
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen3.5:latest",
    "chunk_size": 100,
    "chunk_overlap": 10,
    "system_prompt": None,
    "user_prompt_tpl": None,
    "title_user_prompt_tpl": None,
    "question_true_false_user_prompt_tpl": None,
}

LOGGING_DEFAULTS: dict[str, Any] = {
    "level": "INFO",
}

GAME_DEFAULTS: dict[str, Any] = {
    "language": "es",
    "questions_per_paragraph": 5,
    "correct_to_master": 3,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "theme": "system",
    "app_name": "autotester",
    "auto_refresh": True,
    "ia": deepcopy(IA_DEFAULTS),
    "logging": deepcopy(LOGGING_DEFAULTS),
    "game": deepcopy(GAME_DEFAULTS),
}

_VALID_IA_KEYS = set(IA_DEFAULTS.keys())
_VALID_LOGGING_KEYS = set(LOGGING_DEFAULTS.keys())
_VALID_GAME_KEYS = set(GAME_DEFAULTS.keys())


def _validate_ia(ia: dict[str, Any]) -> None:
    """Raise ValueError if the IA section is invalid.

    ``None`` prompt values are accepted — they mean "use the default".
    """
    unknown = set(ia) - _VALID_IA_KEYS
    if unknown:
        raise ValueError(f"Unknown IA keys: {sorted(unknown)}")
    chunk_size = ia.get("chunk_size", IA_DEFAULTS["chunk_size"])
    chunk_overlap = ia.get("chunk_overlap", IA_DEFAULTS["chunk_overlap"])
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    if not isinstance(chunk_overlap, int) or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be 0 <= overlap < chunk_size")
    for key in _PROMPT_KEYS:
        value = ia.get(key)
        if value is None:
            continue  # None means "use default", valid
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")
        if key in ("user_prompt_tpl", "title_user_prompt_tpl") and "{text}" not in value:
            raise ValueError(f"{key} must contain the {{text}} placeholder")
        if key == "question_true_false_user_prompt_tpl":
            for ph in ("{text}", "{keyword}", "{target_response}", "{language}"):
                if ph not in value:
                    raise ValueError(f"{key} must contain the {ph} placeholder")


def _validate_game(game_cfg: dict[str, Any]) -> None:
    """Raise ValueError if the game section is invalid."""
    unknown = set(game_cfg) - _VALID_GAME_KEYS
    if unknown:
        raise ValueError(f"Unknown game keys: {sorted(unknown)}")
    language = game_cfg.get("language", GAME_DEFAULTS["language"])
    if not isinstance(language, str) or not language.strip():
        raise ValueError("game.language must be a non-empty string")
    qpp = game_cfg.get("questions_per_paragraph", GAME_DEFAULTS["questions_per_paragraph"])
    if not isinstance(qpp, int) or qpp <= 0:
        raise ValueError("game.questions_per_paragraph must be a positive integer")
    ctm = game_cfg.get("correct_to_master", GAME_DEFAULTS["correct_to_master"])
    if not isinstance(ctm, int) or ctm <= 0:
        raise ValueError("game.correct_to_master must be a positive integer")

def _validate_logging(logging_cfg: dict[str, Any]) -> None:
    """Raise ValueError if the logging section is invalid."""
    unknown = set(logging_cfg) - _VALID_LOGGING_KEYS
    if unknown:
        raise ValueError(f"Unknown logging keys: {sorted(unknown)}")
    level = logging_cfg.get("level", LOGGING_DEFAULTS["level"])
    if not isinstance(level, str) or level.upper() not in VALID_LOG_LEVELS:
        raise ValueError(f"Invalid log level: {level!r}")


class ConfigManager:
    """Read and write the application configuration YAML file."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)

    def load(self) -> dict[str, Any]:
        """Load the current configuration, merging defaults for missing keys.

        Persists the file with default values when missing, empty or corrupt
        so callers can rely on a valid configuration on disk afterwards.
        """
        data: dict[str, Any] = {}
        if self.config_path.exists():
            try:
                raw = self.config_path.read_text(encoding="utf-8")
                if raw.strip():
                    parsed = yaml.safe_load(raw)
                    if isinstance(parsed, dict):
                        data = parsed
            except (yaml.YAMLError, OSError):
                data = {}

        merged = deepcopy(DEFAULT_CONFIG)
        merged.update(data)

        if merged.get("theme") not in VALID_THEMES:
            merged["theme"] = DEFAULT_CONFIG["theme"]

        # Merge IA defaults for missing keys and sanitize invalid input.
        ia = merged.get("ia")
        if not isinstance(ia, dict):
            ia = {}
        ia_merged = deepcopy(IA_DEFAULTS)
        ia_merged.update({k: v for k, v in ia.items() if k in _VALID_IA_KEYS})
        # Resolve None prompts to their Python-level defaults.
        for key in _PROMPT_KEYS:
            if ia_merged.get(key) is None:
                ia_merged[key] = _PROMPT_DEFAULTS[key]
        # Coerce numeric fields to int if they came in as strings.
        ia_merged["chunk_size"] = int(ia_merged["chunk_size"])
        ia_merged["chunk_overlap"] = int(ia_merged["chunk_overlap"])
        merged["ia"] = ia_merged

        # Merge logging defaults for missing keys and sanitize invalid input.
        logging_cfg = merged.get("logging")
        if not isinstance(logging_cfg, dict):
            logging_cfg = {}
        logging_merged = deepcopy(LOGGING_DEFAULTS)
        logging_merged.update(
            {k: v for k, v in logging_cfg.items() if k in _VALID_LOGGING_KEYS}
        )
        # Normalize the level value to an uppercase string.
        logging_merged["level"] = str(logging_merged["level"]).upper()
        merged["logging"] = logging_merged

        # Merge game defaults for missing keys and sanitize invalid input.
        game_cfg = merged.get("game")
        if not isinstance(game_cfg, dict):
            game_cfg = {}
        game_merged = deepcopy(GAME_DEFAULTS)
        game_merged.update(
            {k: v for k, v in game_cfg.items() if k in _VALID_GAME_KEYS}
        )
        # Coerce numeric fields to int if they came in as strings.
        game_merged["questions_per_paragraph"] = int(game_merged["questions_per_paragraph"])
        game_merged["correct_to_master"] = int(game_merged["correct_to_master"])
        merged["game"] = game_merged

        if not self.config_path.exists():
            self.save(merged)

        return merged

    def save(self, config: dict[str, Any]) -> None:
        """Persist the given configuration atomically to YAML.

        Prompt values that match the Python-level defaults are stored as
        ``None`` in the YAML so they are not duplicated on disk.
        """
        to_write = deepcopy(config)
        ia = to_write.get("ia")
        if isinstance(ia, dict):
            for key in _PROMPT_KEYS:
                if key in ia and ia[key] == _PROMPT_DEFAULTS.get(key):
                    ia[key] = None
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(to_write, sort_keys=False), encoding="utf-8")
        tmp.replace(self.config_path)

    def update(self, **kwargs: Any) -> dict[str, Any]:
        """Update one or more keys and persist. Returns the new configuration."""
        current = self.load()
        for key, value in kwargs.items():
            if key == "theme" and value not in VALID_THEMES:
                raise ValueError(f"Invalid theme: {value!r}")
            current[key] = value
        self.save(current)
        return current

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key`` or ``default`` if not set."""
        return self.load().get(key, default)

    def update_ia(self, **kwargs: Any) -> dict[str, Any]:
        """Update IA settings and persist. Validates before saving.

        Unknown keys raise ``ValueError``. ``chunk_size`` and ``chunk_overlap``
        must satisfy ``0 <= overlap < size``. Empty or whitespace-only prompt
        values are stored as ``None`` (use default).
        """
        current = self.load()
        ia = deepcopy(current.get("ia") or {})
        # Treat empty prompt values as None (use default).
        for key in _PROMPT_KEYS:
            if key in kwargs:
                value = kwargs[key]
                if value is None or (isinstance(value, str) and not value.strip()):
                    kwargs[key] = None
        ia.update(kwargs)
        _validate_ia(ia)
        current["ia"] = ia
        self.save(current)
        return current

    def update_logging(self, **kwargs: Any) -> dict[str, Any]:
        """Update logging settings and persist. Validates before saving.

        Unknown keys raise ``ValueError``. ``level`` must be one of
        ``VALID_LOG_LEVELS`` (DEBUG/INFO/WARNING/ERROR/CRITICAL).
        """
        current = self.load()
        logging_cfg = deepcopy(current.get("logging") or {})
        logging_cfg.update(kwargs)
        _validate_logging(logging_cfg)
        current["logging"] = logging_cfg
        self.save(current)
        return current

    def update_game(self, **kwargs: Any) -> dict[str, Any]:
        """Update game settings and persist. Validates before saving.

        Unknown keys raise ``ValueError``.
        """
        current = self.load()
        game = deepcopy(current.get("game") or {})
        game.update(kwargs)
        _validate_game(game)
        current["game"] = game
        self.save(current)
        return current

    def reset(self) -> dict[str, Any]:
        """Reset all settings to factory defaults and persist."""
        config = deepcopy(DEFAULT_CONFIG)
        self.save(config)
        return config