"""Persistence helpers for trade and detection records."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from threading import Lock

_counter_lock = Lock()
_counter = 0

logger = logging.getLogger(__name__)


def record_trade(trades_dir: str | Path, trade_info: dict) -> None:
    """Write a trade record to a timestamped JSON file.

    The filename encodes the market_id and current Unix timestamp so that
    multiple trades for the same market do not overwrite each other.

    Args:
        trades_dir: Directory where trade JSON files are stored.
        trade_info: Serialisable dict describing the trade outcome.
    """
    trades_path = Path(trades_dir)
    trades_path.mkdir(parents=True, exist_ok=True)

    global _counter
    market_id = trade_info.get("market_id", "unknown")
    status = trade_info.get("status", "unknown")
    ts = int(time.time())
    with _counter_lock:
        _counter += 1
        seq = _counter

    suffix = "" if status == "success" else f"_{status}"
    filename = trades_path / f"{market_id}{suffix}_{ts}_{seq}.json"

    try:
        with filename.open("w") as fh:
            json.dump(trade_info, fh, indent=2)
        logger.debug("Trade record written to %s", filename)
    except OSError as exc:
        logger.error("Failed to write trade record to %s: %s", filename, exc)


def record_detection(detections_dir: str | Path, detection_info: dict) -> None:
    """Write a keyword detection record to a timestamped JSON file.

    Args:
        detections_dir: Directory where detection JSON files are stored.
        detection_info: Serialisable dict describing the detection event.
    """
    detections_path = Path(detections_dir)
    detections_path.mkdir(parents=True, exist_ok=True)

    global _counter
    market_id = detection_info.get("market_id", "unknown")
    ts = int(time.time())
    with _counter_lock:
        _counter += 1
        seq = _counter
    filename = detections_path / f"{market_id}_{ts}_{seq}.json"

    try:
        with filename.open("w") as fh:
            json.dump(detection_info, fh, indent=2)
        logger.debug("Detection record written to %s", filename)
    except OSError as exc:
        logger.error("Failed to write detection record to %s: %s", filename, exc)
