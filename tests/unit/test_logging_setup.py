"""Tests for blackstar_bot.logging_setup."""

import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock

import pytest

from blackstar_bot.logging_setup import LOG_BACKUP_COUNT, MAX_LOG_BYTES, configure_logging


@pytest.fixture(autouse=True)
def restore_root_handlers():
    """configure_logging mutates the root logger; put it back afterwards."""
    root = logging.getLogger()
    original = list(root.handlers)
    yield
    for handler in list(root.handlers):
        if handler not in original:
            handler.close()
            root.removeHandler(handler)


def _settings(log_file):
    s = MagicMock()
    s.log_file = log_file
    return s


def _added_file_handlers(before):
    return [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, RotatingFileHandler) and h not in before
    ]


def test_configure_logging_adds_rotating_file_handler(tmp_path):
    before = list(logging.getLogger().handlers)
    log_file = tmp_path / "bot.log"

    configure_logging(_settings(log_file))

    handlers = _added_file_handlers(before)
    assert len(handlers) == 1
    assert handlers[0].maxBytes == MAX_LOG_BYTES
    assert handlers[0].backupCount == LOG_BACKUP_COUNT


def test_configure_logging_writes_audit_lines_to_file(tmp_path):
    log_file = tmp_path / "bot.log"
    configure_logging(_settings(log_file))

    logging.getLogger("blackstar_bot.authz").warning("unauthorized_command user_id=%s", 42)

    assert "unauthorized_command user_id=42" in log_file.read_text()


def test_configure_logging_creates_missing_parent_directory(tmp_path):
    log_file = tmp_path / "nested" / "dir" / "bot.log"
    configure_logging(_settings(log_file))

    logging.getLogger("blackstar_bot.authz").warning("hello")

    assert log_file.exists()


def test_configure_logging_skips_file_handler_when_unset():
    before = list(logging.getLogger().handlers)

    configure_logging(_settings(None))

    assert _added_file_handlers(before) == []
