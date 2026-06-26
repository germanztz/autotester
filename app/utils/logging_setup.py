"""Centralized logging configuration for autotester.

A single namespaced logger (``autotester``) writes to stderr at a level
read from ``config.yaml`` (default ``INFO``). Setup is idempotent so it
can be safely called from the app factory and from tests.
"""
from __future__ import annotations

import logging
import sys
from typing import Final


VALID_LOG_LEVELS: Final[tuple[str, ...]] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)

LOGGER_NAME: Final[str] = "autotester"

_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"

_configured: bool = False


def _coerce_level(level: str) -> str:
    """Normalize a level string and raise ``ValueError`` on invalid input.

    Callers that want to allow a default should pass the literal default
    string (e.g. ``"INFO"``) explicitly. An empty string is treated as
    invalid because it is most likely a bug in the caller.
    """
    upper = (level or "").upper()
    if upper not in VALID_LOG_LEVELS:
        raise ValueError(f"Invalid log level: {level!r}")
    return upper


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure the autotester logger with a single stderr StreamHandler.

    Idempotent: re-calling clears previous handlers and reapplies the
    new level, which is useful for tests and runtime reconfiguration.
    """
    level_name = _coerce_level(level)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level_name)

    # Idempotency: drop handlers added by previous setup calls.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    # Intentionally allow propagation so libraries that attach to the
    # root logger (e.g. pytest's caplog) can still capture our records.
    # In production this means duplicate output only if someone else
    # also configures the root logger; that is a deployment concern,
    # not a library concern.

    global _configured
    _configured = True
    return logger


def get_logger() -> logging.Logger:
    """Return the autotester logger, calling ``setup_logging`` if needed."""
    global _configured
    if not _configured:
        setup_logging()
    return logging.getLogger(LOGGER_NAME)


def reset_logger() -> None:
    """Remove all handlers and reset the configured flag.

    Intended for tests that need a clean logger state. Not part of the
    public runtime API.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    _configured = False
