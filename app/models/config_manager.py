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

IA_DEFAULTS: dict[str, Any] = {
    "ollama_url": "http://localhost:11434",
    "embedding_model": "qwen3-embedding:4b",
    "chunk_size": 500,
    "chunk_overlap": 50,
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