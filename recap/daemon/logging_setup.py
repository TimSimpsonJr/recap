"""Daemon logging setup with daily rotation and configurable retention."""
from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_FILENAME = "recap.log"


def _resolve_log_level() -> int:
    """Return the log level from RECAP_LOG_LEVEL, falling back to INFO.

    Unknown values fall back to INFO so a typo in the env var cannot
    silently disable logging. Known values are the standard logging
    level names (DEBUG, INFO, WARNING, ERROR, CRITICAL), case-insensitive.
    """
    name = os.environ.get("RECAP_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, name, None)
    if not isinstance(level, int):
        return logging.INFO
    return level


def setup_logging(log_dir: Path, retention_days: int) -> None:
    """Configure the ``recap`` logger with file rotation and console output.

    Creates *log_dir* if it doesn't exist, attaches a daily-rotating file
    handler and a stream handler, and purges stale log files that exceed
    *retention_days*.  Safe to call multiple times -- duplicate handlers are
    not added.

    Log level is read from ``RECAP_LOG_LEVEL`` (default INFO). Set
    ``RECAP_LOG_LEVEL=DEBUG`` to activate diagnostic instrumentation like
    the Teams-detection logging added for issue #30.
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("recap")
    logger.setLevel(_resolve_log_level())

    # Idempotency: skip if handlers already attached
    handler_types = {type(h).__name__ for h in logger.handlers}
    if "TimedRotatingFileHandler" in handler_types and "StreamHandler" in handler_types:
        return

    formatter = logging.Formatter(_LOG_FORMAT)

    # File handler with daily rotation
    if "TimedRotatingFileHandler" not in handler_types:
        file_handler = TimedRotatingFileHandler(
            filename=log_dir / _LOG_FILENAME,
            when="midnight",
            backupCount=retention_days,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Console handler
    if "StreamHandler" not in handler_types:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    # Purge old log files beyond retention (pre-existing logs from before
    # rotation was configured).
    _purge_old_logs(log_dir, retention_days)


def _purge_old_logs(log_dir: Path, retention_days: int) -> None:
    """Remove rotated log files that exceed the retention window."""
    import time

    cutoff = time.time() - (retention_days * 86_400)
    for log_file in log_dir.glob("recap.log.*"):
        try:
            if log_file.stat().st_mtime < cutoff:
                log_file.unlink()
        except OSError as e:
            print(f"Could not delete old log file {log_file}: {e}")
