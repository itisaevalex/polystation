"""Tests for polystation.trading.recorder — record_trade() and record_detection()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from polystation.trading.recorder import record_detection, record_trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _only_json_file(directory: Path) -> Path:
    """Assert exactly one JSON file exists in *directory* and return it."""
    files = list(directory.glob("*.json"))
    assert len(files) == 1, f"Expected 1 JSON file, found {len(files)}: {files}"
    return files[0]


# ---------------------------------------------------------------------------
# record_trade()
# ---------------------------------------------------------------------------

class TestRecordTrade:

    def test_creates_json_file(self, tmp_path: Path) -> None:
        trades_dir = tmp_path / "trades"
        trades_dir.mkdir()
        info = {
            "market_id": "crypto_market",
            "status": "success",
            "timestamp": "2026-01-20T12:00:00",
        }
        record_trade(trades_dir, info)
        assert any(trades_dir.glob("*.json"))

    def test_filename_contains_market_id(self, tmp_path: Path) -> None:
        trades_dir = tmp_path / "trades"
        trades_dir.mkdir()
        info = {
            "market_id": "doge_market",
            "status": "success",
            "timestamp": "2026-01-20T12:00:00",
        }
        record_trade(trades_dir, info)
        file = _only_json_file(trades_dir)
        assert "doge_market" in file.name

    def test_filename_contains_status(self, tmp_path: Path) -> None:
        trades_dir = tmp_path / "trades"
        trades_dir.mkdir()
        info = {
            "market_id": "crypto_market",
            "status": "failed",
            "timestamp": "2026-01-20T12:00:00",
        }
        record_trade(trades_dir, info)
        file = _only_json_file(trades_dir)
        assert "failed" in file.name

    def test_file_contains_expected_fields(self, tmp_path: Path) -> None:
        trades_dir = tmp_path / "trades"
        trades_dir.mkdir()
        info = {
            "market_id": "crypto_market",
            "market_name": "Crypto/Bitcoin Mention",
            "status": "success",
            "timestamp": "2026-01-20T12:00:00",
            "detected_keyword": "bitcoin",
        }
        record_trade(trades_dir, info)
        file = _only_json_file(trades_dir)
        data = json.loads(file.read_text(encoding="utf-8"))
        for key, value in info.items():
            assert data[key] == value

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        trades_dir = tmp_path / "trades" / "nested"
        assert not trades_dir.exists()
        info = {
            "market_id": "crypto_market",
            "status": "success",
            "timestamp": "2026-01-20T12:00:00",
        }
        record_trade(trades_dir, info)
        assert trades_dir.is_dir()
        assert any(trades_dir.glob("*.json"))

    def test_written_file_is_valid_json(self, tmp_path: Path) -> None:
        trades_dir = tmp_path / "trades"
        trades_dir.mkdir()
        record_trade(trades_dir, {"market_id": "m", "status": "ok", "timestamp": "t"})
        file = _only_json_file(trades_dir)
        # Should not raise
        parsed = json.loads(file.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)

    def test_multiple_trades_produce_distinct_files(self, tmp_path: Path) -> None:
        trades_dir = tmp_path / "trades"
        trades_dir.mkdir()
        for status in ("success", "failed", "error"):
            record_trade(
                trades_dir,
                {"market_id": "crypto_market", "status": status, "timestamp": "t"},
            )
        files = list(trades_dir.glob("*.json"))
        assert len(files) == 3
        assert len({f.name for f in files}) == 3  # all unique


# ---------------------------------------------------------------------------
# record_detection()
# ---------------------------------------------------------------------------

class TestRecordDetection:

    def test_creates_json_file(self, tmp_path: Path) -> None:
        detections_dir = tmp_path / "detections"
        detections_dir.mkdir()
        info = {
            "market_id": "crypto_market",
            "timestamp": "2026-01-20T12:00:00",
            "detected_keyword": "bitcoin",
            "full_text": "trump mentioned bitcoin",
        }
        record_detection(detections_dir, info)
        assert any(detections_dir.glob("*.json"))

    def test_filename_contains_market_id(self, tmp_path: Path) -> None:
        detections_dir = tmp_path / "detections"
        detections_dir.mkdir()
        info = {
            "market_id": "greenland_market",
            "timestamp": "2026-01-20T12:00:00",
        }
        record_detection(detections_dir, info)
        file = _only_json_file(detections_dir)
        assert "greenland_market" in file.name

    def test_file_contains_expected_fields(self, tmp_path: Path) -> None:
        detections_dir = tmp_path / "detections"
        detections_dir.mkdir()
        info = {
            "market_id": "crypto_market",
            "market_name": "Crypto/Bitcoin Mention",
            "timestamp": "2026-01-20T12:00:00",
            "detected_keyword": "crypto",
            "full_text": "trump talked about crypto",
        }
        record_detection(detections_dir, info)
        file = _only_json_file(detections_dir)
        data = json.loads(file.read_text(encoding="utf-8"))
        for key, value in info.items():
            assert data[key] == value

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        detections_dir = tmp_path / "detections" / "nested"
        assert not detections_dir.exists()
        record_detection(
            detections_dir,
            {"market_id": "crypto_market", "timestamp": "2026-01-20T12:00:00"},
        )
        assert detections_dir.is_dir()
        assert any(detections_dir.glob("*.json"))

    def test_written_file_is_valid_json(self, tmp_path: Path) -> None:
        detections_dir = tmp_path / "detections"
        detections_dir.mkdir()
        record_detection(
            detections_dir,
            {"market_id": "m", "timestamp": "t", "detected_keyword": "kw"},
        )
        file = _only_json_file(detections_dir)
        parsed = json.loads(file.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)

    def test_filename_contains_timestamp(self, tmp_path: Path) -> None:
        """The filename should embed a timestamp component so files are ordered."""
        detections_dir = tmp_path / "detections"
        detections_dir.mkdir()
        record_detection(
            detections_dir,
            {"market_id": "crypto_market", "timestamp": "2026-01-20T12:00:00"},
        )
        file = _only_json_file(detections_dir)
        # File name should have more content than just the market_id
        assert file.stem != "crypto_market"

    def test_multiple_detections_produce_distinct_files(self, tmp_path: Path) -> None:
        detections_dir = tmp_path / "detections"
        detections_dir.mkdir()
        for i in range(3):
            record_detection(
                detections_dir,
                {
                    "market_id": "crypto_market",
                    "timestamp": f"2026-01-20T12:00:0{i}",
                    "detected_keyword": "bitcoin",
                },
            )
        files = list(detections_dir.glob("*.json"))
        assert len(files) == 3
        assert len({f.name for f in files}) == 3
