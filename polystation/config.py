"""Configuration loading from YAML files."""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and provides access to application configuration from YAML files.

    Args:
        config_dir: Directory containing configuration files. Defaults to "config".
    """

    def __init__(self, config_dir: str | Path = "config") -> None:
        self.config_dir = Path(config_dir)
        self.settings: dict[str, Any] = {}
        self.markets: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, Any]] = {}

        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "sources").mkdir(parents=True, exist_ok=True)

        self._load_settings()
        self._load_markets()
        self._load_sources()

        logger.info(
            "Configuration loaded: %d markets, %d sources",
            len(self.markets),
            len(self.sources),
        )

    def _load_yaml(self, filepath: Path) -> dict[str, Any]:
        """Load a YAML file, returning an empty dict if missing or on error."""
        if not filepath.exists():
            logger.warning("Configuration file not found: %s", filepath)
            return {}
        try:
            with filepath.open("r") as fh:
                return yaml.safe_load(fh) or {}
        except Exception as exc:
            logger.error("Error loading configuration from %s: %s", filepath, exc)
            return {}

    def _load_settings(self) -> None:
        self.settings = self._load_yaml(self.config_dir / "settings.yaml")

    def _load_markets(self) -> None:
        self.markets = self._load_yaml(self.config_dir / "markets.yaml")

    def _load_sources(self) -> None:
        sources_dir = self.config_dir / "sources"
        for yaml_file in sources_dir.glob("*.yaml"):
            source_name = yaml_file.stem
            self.sources[source_name] = self._load_yaml(yaml_file)

    def get_setting(self, section: str, key: str, default: Any = None) -> Any:
        """Return a setting value from a section, or *default* if absent."""
        section_data = self.settings.get(section, {})
        return section_data.get(key, default)

    def get_market(self, market_id: str) -> dict[str, Any] | None:
        """Return market configuration for *market_id*, or None if not found."""
        return self.markets.get(market_id)

    def get_markets(self) -> dict[str, dict[str, Any]]:
        """Return all market configurations."""
        return self.markets

    def get_enabled_markets(self) -> dict[str, dict[str, Any]]:
        """Return only markets that are not explicitly disabled."""
        return {k: v for k, v in self.markets.items() if not v.get("disabled", False)}

    def get_source_config(self, source_name: str) -> dict[str, Any]:
        """Return source configuration for *source_name*, or an empty dict."""
        return self.sources.get(source_name, {})

    def get_markets_for_source(
        self,
        source_name: str,
        channel_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return markets configured for a specific source and optional channel.

        Args:
            source_name: The source identifier (e.g. "youtube", "twitter").
            channel_name: Optional channel name to narrow results.

        Returns:
            List of market configuration dicts.
        """
        source_config = self.get_source_config(source_name)
        if not source_config:
            return []

        if channel_name and "channels" in source_config:
            for channel in source_config["channels"]:
                if channel["name"] == channel_name and channel.get("active", True):
                    return [
                        self.markets[mid]
                        for mid in channel.get("markets", [])
                        if mid in self.markets
                    ]

        return list(self.get_enabled_markets().values())

    def ensure_paths(self) -> None:
        """Create all configured output directories if they do not exist."""
        for path_str in self.settings.get("paths", {}).values():
            Path(path_str).mkdir(parents=True, exist_ok=True)


@functools.lru_cache(maxsize=1)
def get_config(config_dir: str = "config") -> ConfigLoader:
    """Return a cached singleton ConfigLoader instance.

    Args:
        config_dir: Directory containing configuration files.
    """
    return ConfigLoader(config_dir)
