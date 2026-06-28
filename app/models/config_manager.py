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
    "You are a semantic text analyzer. Your task is to group related concepts "
    "together, maintain the original meaning and flow, and extract key keywords "
    "from each text chunk."
)

_DEFAULT_USER_PROMPT_TPL = (
    'Analyze the following text chunk. Group related concepts, maintain the '
    'original meaning and coherence, and extract 3-7 keywords that represent '
    'the main topics.\n\n'
    'IMPORTANT: Never translate the text content or the keywords. They must '
    'remain in the original document language.\n\n'
    'Text:\n{text}\n\n'
    'Return ONLY valid JSON with exactly these fields (no markdown, no extra text):\n'
    '{{"original_text": "the semantically grouped text", "text_keywords": ["kw1", "kw2", ...]}}'
)

_DEFAULT_TITLE_SYSTEM_PROMPT = (
    "You are a helpful assistant that generates concise, descriptive project "
    "titles from document content. Respond with only the title, no extra text."
)

_DEFAULT_TITLE_USER_PROMPT_TPL = (
    "Based on the following text, generate a short title of 1 to 7 words that "
    "represents the project. The title must be syntactically correct (not a "
    "single concatenated word) and may include emojis to make it expressive.\n\n"
    "{text}\n\nTitle:"
)

IA_DEFAULTS: dict[str, Any] = {
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen3.5:latest",
    "chunk_size": 400,
    "chunk_overlap": 50,
    "system_prompt": _DEFAULT_SYSTEM_PROMPT,
    "user_prompt_tpl": _DEFAULT_USER_PROMPT_TPL,
    "title_system_prompt": _DEFAULT_TITLE_SYSTEM_PROMPT,
    "title_user_prompt_tpl": _DEFAULT_TITLE_USER_PROMPT_TPL,
}

LOGGING_DEFAULTS: dict[str, Any] = {
    "level": "INFO",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "theme": "system",
    "app_name": "autotester",
    "auto_refresh": True,
    "ia": deepcopy(IA_DEFAULTS),
    "logging": deepcopy(LOGGING_DEFAULTS),
}

_VALID_IA_KEYS = set(IA_DEFAULTS.keys())
_VALID_LOGGING_KEYS = set(LOGGING_DEFAULTS.keys())


def _validate_ia(ia: dict[str, Any]) -> None:
    """Raise ValueError if the IA section is invalid."""
    unknown = set(ia) - _VALID_IA_KEYS
    if unknown:
        raise ValueError(f"Unknown IA keys: {sorted(unknown)}")
    chunk_size = ia.get("chunk_size", IA_DEFAULTS["chunk_size"])
    chunk_overlap = ia.get("chunk_overlap", IA_DEFAULTS["chunk_overlap"])
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    if not isinstance(chunk_overlap, int) or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be 0 <= overlap < chunk_size")
    system_prompt = ia.get("system_prompt", "")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ValueError("system_prompt must be a non-empty string")
    user_prompt_tpl = ia.get("user_prompt_tpl", "")
    if not isinstance(user_prompt_tpl, str) or not user_prompt_tpl.strip():
        raise ValueError("user_prompt_tpl must be a non-empty string")
    if "{text}" not in user_prompt_tpl:
        raise ValueError("user_prompt_tpl must contain the {text} placeholder")
    title_system_prompt = ia.get("title_system_prompt", "")
    if not isinstance(title_system_prompt, str) or not title_system_prompt.strip():
        raise ValueError("title_system_prompt must be a non-empty string")
    title_user_prompt_tpl = ia.get("title_user_prompt_tpl", "")
    if not isinstance(title_user_prompt_tpl, str) or not title_user_prompt_tpl.strip():
        raise ValueError("title_user_prompt_tpl must be a non-empty string")
    if "{text}" not in title_user_prompt_tpl:
        raise ValueError("title_user_prompt_tpl must contain the {text} placeholder")


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

        if not self.config_path.exists():
            self.save(merged)

        return merged

    def save(self, config: dict[str, Any]) -> None:
        """Persist the given configuration atomically to YAML."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
        must satisfy ``0 <= overlap < size``.
        """
        current = self.load()
        ia = deepcopy(current.get("ia") or {})
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