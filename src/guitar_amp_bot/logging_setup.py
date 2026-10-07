"""Logging configuration shared by the bot entry points.

The unauthorized-command warning is an audit record, so it must survive the
process that wrote it. ``LOG_FILE`` adds a rotating file handler alongside the
default stderr output.

Call sites attach context with ``extra={...}``; ``ExtrasFormatter`` appends
those fields as ``key=value`` so they are not silently dropped.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guitar_amp_bot.config import Settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3

# Every attribute a plain LogRecord carries, plus those Formatter adds; anything
# else on a record arrived through ``extra=``.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
}


class ExtrasFormatter(logging.Formatter):
    """Format records with their ``extra=`` fields appended as ``key=value``."""

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802 - stdlib name
        """Render the base line, then append the extras before any traceback."""
        line = super().formatMessage(record)
        extras = [
            f"{key}={_render(value)}"
            for key, value in vars(record).items()
            if key not in _STANDARD_ATTRS and not key.startswith("_")
        ]
        return f"{line} {' '.join(extras)}" if extras else line


def _render(value: object) -> str:
    """Keep each field one token: quote values with whitespace or quotes."""
    text = str(value)
    if not text or any(ch.isspace() or ch in "\"'=" for ch in text):
        return repr(text)
    return text


def configure_logging(settings: Settings) -> None:
    """Log to stderr, plus a rotating file when ``LOG_FILE`` is configured.

    A log path that cannot be opened raises rather than falling back to stderr
    only: an audit trail that silently is not written is worse than a bot that
    refuses to start.
    """
    formatter = ExtrasFormatter(LOG_FORMAT)
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    # A no-op when the root logger already has handlers (e.g. under pytest).
    logging.basicConfig(handlers=[stderr_handler])
    # Set explicitly: basicConfig ignores level when it does nothing.
    logging.getLogger().setLevel(settings.log_level)
    if settings.log_file is None:
        return

    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
