"""Tests for app.utils.logging_setup."""
from __future__ import annotations

import logging
import sys

import pytest

from app.utils.logging_setup import (
    LOGGER_NAME,
    VALID_LOG_LEVELS,
    get_logger,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_logger():
    """Ensure each test starts with a clean logger state."""
    from app.utils import logging_setup

    logging_setup.reset_logger()
    yield
    logging_setup.reset_logger()


class TestSetupLogging:
    def test_returns_logger_with_correct_level(self):
        logger = setup_logging("DEBUG")
        assert logger.level == logging.DEBUG

    def test_returns_named_autotester_logger(self):
        logger = setup_logging("INFO")
        assert logger.name == LOGGER_NAME

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_accepts_all_valid_levels(self, level: str):
        logger = setup_logging(level)
        assert logger.level == getattr(logging, level)

    @pytest.mark.parametrize("level", ["FOO", "trace", "verbose", ""])
    def test_rejects_invalid_levels(self, level: str):
        with pytest.raises(ValueError):
            setup_logging(level)

    def test_invalid_level_via_default_returns_logger(self):
        # Calling get_logger with no setup should not raise; defaults to INFO.
        logger = get_logger()
        assert logger.level == logging.INFO

    def test_attaches_stdout_handler(self):
        logger = setup_logging("INFO")
        assert len(logger.handlers) == 1
        handler = logger.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stdout

    def test_handler_has_formatter(self):
        logger = setup_logging("INFO")
        handler = logger.handlers[0]
        assert handler.formatter is not None

    def test_is_idempotent(self):
        setup_logging("INFO")
        setup_logging("DEBUG")
        logger = logging.getLogger(LOGGER_NAME)
        assert len(logger.handlers) == 1
        assert logger.level == logging.DEBUG

    def test_propagate_is_enabled_for_testability(self):
        logger = setup_logging("INFO")
        # Propagate is left enabled so libraries like pytest's caplog
        # can capture our records. The risk of duplicate output is
        # a deployment concern, not a library concern.
        assert logger.propagate is True

    def test_level_case_insensitive(self):
        logger = setup_logging("warning")
        assert logger.level == logging.WARNING


class TestGetLogger:
    def test_returns_singleton(self):
        setup_logging("INFO")
        a = get_logger()
        b = get_logger()
        assert a is b

    def test_returns_logger_even_without_setup(self):
        logger = get_logger()
        assert isinstance(logger, logging.Logger)
        assert logger.name == LOGGER_NAME


class TestValidLogLevels:
    def test_exports_standard_levels(self):
        assert VALID_LOG_LEVELS == ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
