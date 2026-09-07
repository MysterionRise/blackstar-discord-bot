"""Logging configuration shared by the bot entry points.

The unauthorized-command warning is an audit record, so it must survive the
process that wrote it. ``LOG_FILE`` adds a rotating file handler alongside the
default stderr output.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from blackstar_bot.config import Settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


def configure_logging(settings: Settings) -> None:
    """Log to stderr, plus a rotating file when ``LOG_FILE`` is configured.

    A log path that cannot be opened raises rather than falling back to stderr
    only: an audit trail that silently is not written is worse than a bot that
    refuses to start.
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    if settings.log_file is None:
        return

    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
