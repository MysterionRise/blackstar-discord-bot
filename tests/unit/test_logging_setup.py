"""Tests for blackstar_bot.logging_setup."""

import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock

import pytest

from blackstar_bot.logging_setup import (
    LOG_BACKUP_COUNT,
    LOG_FORMAT,
    MAX_LOG_BYTES,
    ExtrasFormatter,
    configure_logging,
)


@pytest.fixture(autouse=True)
def restore_root_handlers():
    """configure_logging mutates the root logger; put it back afterwards."""
    root = logging.getLogger()
    original = list(root.handlers)
    original_level = root.level
    yield
    root.setLevel(original_level)
    for handler in list(root.handlers):
        if handler not in original:
            handler.close()
            root.removeHandler(handler)


def _settings(log_file, log_level="INFO"):
    s = MagicMock()
    s.log_file = log_file
    s.log_level = log_level
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


def _record(msg="stream_config", exc_info=None, **extra):
    record = logging.LogRecord("blackstar_bot.test", logging.INFO, __file__, 1, msg, (), exc_info)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_extras_formatter_appends_extra_fields():
    """extra= fields used to be dropped, so DEBUG_CONFIG lines carried no values."""
    line = ExtrasFormatter(LOG_FORMAT).format(
        _record(backend="sounddevice", device="Blackstar ID:Core V4", attempt=2)
    )

    assert line.endswith(
        "stream_config backend=sounddevice device='Blackstar ID:Core V4' attempt=2"
    )


def test_extras_formatter_leaves_plain_records_unchanged():
    # One record for both formatters: two records can straddle a millisecond
    # boundary and differ in their timestamps.
    record = _record("plain_message")

    assert ExtrasFormatter(LOG_FORMAT).format(record) == logging.Formatter(LOG_FORMAT).format(
        record
    )


def test_extras_formatter_omits_standard_record_attributes():
    line = ExtrasFormatter(LOG_FORMAT).format(_record(count=3))

    for standard in ("lineno=", "threadName=", "taskName=", "process=", "msecs="):
        assert standard not in line
    assert line.endswith("count=3")


def test_extras_formatter_keeps_traceback_after_the_fields():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        line = ExtrasFormatter(LOG_FORMAT).format(
            _record("playback_error", sys.exc_info(), error="x")
        )

    first_line, rest = line.split("\n", 1)
    assert first_line.endswith("playback_error error=x")
    assert rest.startswith("Traceback")


def test_configure_logging_applies_log_level():
    configure_logging(_settings(None, log_level="DEBUG"))

    assert logging.getLogger().level == logging.DEBUG


def test_file_handler_writes_extra_fields(tmp_path):
    log_file = tmp_path / "bot.log"
    configure_logging(_settings(log_file))

    logging.getLogger("blackstar_bot.bot_sounddevice").warning(
        "voice_connect_failed", extra={"channel": "General", "attempt": 2}
    )

    assert "voice_connect_failed channel=General attempt=2" in log_file.read_text()
