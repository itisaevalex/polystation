"""Shared pytest fixtures for the polystation test suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: Any) -> None:
    """Serialise *data* as YAML and write it to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_settings() -> dict:
    """Minimal settings dict mirroring config/settings.yaml."""
    return {
        "trading": {
            "prevent_duplicate_trades": True,
            "max_daily_volume": 5000,
            "default_slippage_tolerance": 5,
            "require_confirmation": False,
            "order_timeout": 10,
        },
        "speech": {
            "chunk_size": 1,
            "save_detections": True,
            "sample_rate": 16000,
            "min_confidence": 0.7,
            "model_name": "vosk-model-small-en-us-0.15",
            "exact_matching": False,
        },
        "paths": {
            "logs": "logs",
            "trades": "trades",
            "detections": "detections",
            "models": "models",
        },
        "app": {
            "debug": False,
            "auto_restart": True,
            "notifications": {"enabled": False, "email": ""},
            "record_all_transcripts": False,
        },
    }


@pytest.fixture()
def sample_markets() -> dict:
    """Three test markets covering both trigger types and disabled filtering."""
    return {
        "crypto_market": {
            "name": "Crypto/Bitcoin Mention",
            "token_id": "111111111111111111111111111111111111111111111111111111111111111111111111111",
            "keywords": ["crypto", "bitcoin", "cryptocurrency"],
            "trigger_type": "any",
            "side": "BUY",
            "price": 0.9,
            "size": 100,
        },
        "greenland_market": {
            "name": "Greenland Mention",
            "token_id": "222222222222222222222222222222222222222222222222222222222222222222222222222",
            "keywords": ["greenland"],
            "trigger_type": "exact",
            "side": "BUY",
            "price": 0.8,
            "size": 50,
        },
        "disabled_market": {
            "name": "Disabled Market",
            "token_id": "333333333333333333333333333333333333333333333333333333333333333333333333333",
            "keywords": ["disabled"],
            "trigger_type": "any",
            "side": "BUY",
            "price": 0.5,
            "size": 10,
            "disabled": True,
        },
    }


@pytest.fixture()
def tmp_config_dir(tmp_path: Path, sample_settings: dict, sample_markets: dict) -> Path:
    """Temporary config directory populated with sample YAML files.

    Layout mirrors the real ``config/`` directory:

    .. code-block::

        <tmp>/config/
            settings.yaml
            markets.yaml
            sources/
                youtube.yaml
                twitter.yaml
                radio.yaml
    """
    config_dir = tmp_path / "config"

    # settings.yaml
    _write_yaml(config_dir / "settings.yaml", sample_settings)

    # markets.yaml
    _write_yaml(config_dir / "markets.yaml", sample_markets)

    # sources/youtube.yaml
    youtube_cfg = {
        "default_url": "https://www.youtube.com/watch?v=TEST",
        "channels": [
            {
                "name": "Test Channel",
                "id": "UCtest",
                "active": True,
                "markets": ["crypto_market"],
            },
            {
                "name": "Inactive Channel",
                "id": "UCinactive",
                "active": False,
                "markets": ["greenland_market"],
            },
        ],
        "ytdlp_options": {"format": "bestaudio", "quiet": True, "no_warnings": True},
        "audio": {"codec": "pcm_s16le", "sample_rate": 16000, "channels": 1},
        "poll_interval": 300,
        "reconnect": {"enabled": True, "max_attempts": 5, "delay": 10},
    }
    _write_yaml(config_dir / "sources" / "youtube.yaml", youtube_cfg)

    # sources/twitter.yaml  (real file uses assignment syntax – we use proper YAML)
    twitter_cfg = {
        "default_url": "https://x.com/i/broadcasts/TEST",
        "ytdlp_options": {"format": "audio_only/audio/worst", "quiet": True},
        "audio": {"codec": "pcm_s16le", "sample_rate": 16000, "channels": 1},
    }
    _write_yaml(config_dir / "sources" / "twitter.yaml", twitter_cfg)

    # sources/radio.yaml
    radio_cfg = {
        "default_url": "https://streams.example.com/radio.mp3",
        "audio": {"codec": "pcm_s16le", "sample_rate": 16000, "channels": 1},
        "buffer_size": 4096,
    }
    _write_yaml(config_dir / "sources" / "radio.yaml", radio_cfg)

    return config_dir
