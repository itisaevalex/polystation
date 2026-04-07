"""Tests for polystation.config.ConfigLoader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from polystation.config import ConfigLoader


# ---------------------------------------------------------------------------
# Loading YAML files
# ---------------------------------------------------------------------------

class TestConfigLoaderInit:
    """ConfigLoader reads the three standard YAML files on construction."""

    def test_loads_settings(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        assert loader.settings != {}

    def test_loads_markets(self, tmp_config_dir: Path, sample_markets: dict) -> None:
        loader = ConfigLoader(tmp_config_dir)
        assert set(loader.markets.keys()) == set(sample_markets.keys())

    def test_loads_sources(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        # At least youtube, twitter, radio should be present
        assert "youtube" in loader.sources
        assert "twitter" in loader.sources
        assert "radio" in loader.sources

    def test_missing_config_dir_returns_empty(self, tmp_path: Path) -> None:
        """ConfigLoader with a non-existent directory must not raise."""
        missing = tmp_path / "no_such_dir"
        loader = ConfigLoader(missing)
        # All dicts should be empty – no crash
        assert loader.settings == {}
        assert loader.markets == {}
        assert loader.sources == {}

    def test_missing_individual_yaml_returns_empty(self, tmp_path: Path) -> None:
        """A config dir that has no markets.yaml yields an empty markets dict."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "sources").mkdir()
        # Only write settings – omit markets and sources
        (config_dir / "settings.yaml").write_text(
            yaml.dump({"app": {"debug": False}}), encoding="utf-8"
        )
        loader = ConfigLoader(config_dir)
        assert loader.markets == {}


# ---------------------------------------------------------------------------
# get_setting()
# ---------------------------------------------------------------------------

class TestGetSetting:

    def test_returns_existing_value(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        assert loader.get_setting("trading", "prevent_duplicate_trades") is True

    def test_returns_default_for_missing_key(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        result = loader.get_setting("trading", "nonexistent_key", default="FALLBACK")
        assert result == "FALLBACK"

    def test_returns_default_for_missing_section(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        result = loader.get_setting("no_such_section", "key", default=42)
        assert result == 42

    def test_default_is_none_when_not_supplied(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        result = loader.get_setting("trading", "nonexistent_key")
        assert result is None

    def test_returns_integer_value(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        assert loader.get_setting("speech", "sample_rate") == 16000

    def test_returns_string_value(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        model = loader.get_setting("speech", "model_name")
        assert isinstance(model, str)
        assert model != ""


# ---------------------------------------------------------------------------
# get_market() / get_markets()
# ---------------------------------------------------------------------------

class TestGetMarket:

    def test_returns_known_market(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        market = loader.get_market("crypto_market")
        assert market is not None
        assert market["name"] == "Crypto/Bitcoin Mention"

    def test_returns_none_for_unknown_market(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        assert loader.get_market("totally_unknown_market") is None

    def test_get_markets_returns_all(
        self, tmp_config_dir: Path, sample_markets: dict
    ) -> None:
        loader = ConfigLoader(tmp_config_dir)
        assert set(loader.get_markets().keys()) == set(sample_markets.keys())


# ---------------------------------------------------------------------------
# get_enabled_markets()
# ---------------------------------------------------------------------------

class TestGetEnabledMarkets:

    def test_excludes_disabled_markets(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        enabled = loader.get_enabled_markets()
        assert "disabled_market" not in enabled

    def test_includes_non_disabled_markets(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        enabled = loader.get_enabled_markets()
        assert "crypto_market" in enabled
        assert "greenland_market" in enabled

    def test_count_is_correct(self, tmp_config_dir: Path, sample_markets: dict) -> None:
        loader = ConfigLoader(tmp_config_dir)
        disabled_count = sum(
            1 for m in sample_markets.values() if m.get("disabled", False)
        )
        assert len(loader.get_enabled_markets()) == len(sample_markets) - disabled_count

    def test_all_enabled_when_none_disabled(self, tmp_path: Path) -> None:
        """When no market has disabled=True, all markets are returned."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "sources").mkdir()
        markets = {
            "market_a": {"name": "A", "keywords": ["a"], "trigger_type": "any"},
            "market_b": {"name": "B", "keywords": ["b"], "trigger_type": "any"},
        }
        (config_dir / "markets.yaml").write_text(
            yaml.dump(markets), encoding="utf-8"
        )
        loader = ConfigLoader(config_dir)
        assert len(loader.get_enabled_markets()) == 2


# ---------------------------------------------------------------------------
# get_source_config()
# ---------------------------------------------------------------------------

class TestGetSourceConfig:

    def test_returns_youtube_config(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        cfg = loader.get_source_config("youtube")
        assert cfg is not None
        assert "default_url" in cfg

    def test_returns_twitter_config(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        cfg = loader.get_source_config("twitter")
        assert cfg is not None

    def test_returns_radio_config(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        cfg = loader.get_source_config("radio")
        assert cfg is not None

    def test_returns_empty_dict_for_unknown_source(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        assert loader.get_source_config("telegram") == {}


# ---------------------------------------------------------------------------
# get_markets_for_source()
# ---------------------------------------------------------------------------

class TestGetMarketsForSource:

    def test_without_channel_returns_enabled_markets(
        self, tmp_config_dir: Path
    ) -> None:
        loader = ConfigLoader(tmp_config_dir)
        markets = loader.get_markets_for_source("youtube")
        # Should equal enabled markets list
        assert len(markets) == len(loader.get_enabled_markets())

    def test_with_active_channel_name(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(tmp_config_dir)
        markets = loader.get_markets_for_source("youtube", channel_name="Test Channel")
        # "Test Channel" has only crypto_market
        assert len(markets) == 1
        assert markets[0]["name"] == "Crypto/Bitcoin Mention"

    def test_with_inactive_channel_falls_back_to_enabled(
        self, tmp_config_dir: Path
    ) -> None:
        """Inactive channel is skipped; falls back to all enabled markets."""
        loader = ConfigLoader(tmp_config_dir)
        markets = loader.get_markets_for_source(
            "youtube", channel_name="Inactive Channel"
        )
        assert len(markets) == len(loader.get_enabled_markets())

    def test_with_unknown_source_returns_empty(
        self, tmp_config_dir: Path
    ) -> None:
        loader = ConfigLoader(tmp_config_dir)
        assert loader.get_markets_for_source("nonexistent_source") == []

    def test_with_unknown_channel_falls_back_to_enabled(
        self, tmp_config_dir: Path
    ) -> None:
        """When channel name is given but not found, falls back to all enabled markets."""
        loader = ConfigLoader(tmp_config_dir)
        markets = loader.get_markets_for_source(
            "youtube", channel_name="Unknown Channel"
        )
        # No channels match → falls back to get_enabled_markets()
        assert len(markets) == len(loader.get_enabled_markets())


# ---------------------------------------------------------------------------
# ensure_paths()
# ---------------------------------------------------------------------------

class TestEnsurePaths:

    def test_creates_directories_from_paths_config(
        self, tmp_path: Path, sample_settings: dict
    ) -> None:
        # Override paths to live inside tmp_path
        sample_settings["paths"] = {
            "logs": str(tmp_path / "logs"),
            "trades": str(tmp_path / "trades"),
            "detections": str(tmp_path / "detections"),
        }
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "sources").mkdir()
        (config_dir / "settings.yaml").write_text(
            yaml.dump(sample_settings), encoding="utf-8"
        )
        loader = ConfigLoader(config_dir)
        loader.ensure_paths()

        assert (tmp_path / "logs").is_dir()
        assert (tmp_path / "trades").is_dir()
        assert (tmp_path / "detections").is_dir()
