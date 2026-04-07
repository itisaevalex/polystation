"""Shared logging setup for all audio sources."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_FORMATTER = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5


def _make_logger(name: str, log_path: Path, level: int) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT
    )
    file_handler.setFormatter(_FORMATTER)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(_FORMATTER)

    log = logging.getLogger(name)
    log.setLevel(level)
    # Avoid adding duplicate handlers when called multiple times
    if not log.handlers:
        log.addHandler(file_handler)
        log.addHandler(console_handler)

    return log


def setup_logging(
    source_name: str,
    logs_dir: str | Path,
    debug: bool = False,
) -> tuple[logging.Logger, logging.Logger, logging.Logger]:
    """Set up main, trade, and speech loggers for a named source.

    Args:
        source_name: Identifier for the audio source (e.g. "youtube").
        logs_dir: Directory where log files are written.
        debug: When True, set all loggers to DEBUG level.

    Returns:
        A 3-tuple of (main_logger, trade_logger, speech_logger).
    """
    level = logging.DEBUG if debug else logging.INFO
    logs_path = Path(logs_dir)

    prefix = f"{source_name}_" if source_name else ""

    main_logger = _make_logger(
        f"{prefix}main", logs_path / f"{prefix}main.log", level
    )
    trade_logger = _make_logger(
        f"{prefix}trade", logs_path / f"{prefix}trades.log", level
    )
    speech_logger = _make_logger(
        f"{prefix}speech", logs_path / f"{prefix}speech.log", level
    )

    return main_logger, trade_logger, speech_logger
