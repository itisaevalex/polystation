"""Keyword matching against configured Polymarket markets."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Represents a single keyword detection event.

    Attributes:
        market_id: The market identifier from configuration.
        market_name: Human-readable market name.
        keyword: The specific keyword that matched.
        full_text: The full recognised utterance.
        timestamp: UTC time of detection.
    """

    market_id: str
    market_name: str
    keyword: str
    full_text: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "market_id": self.market_id,
            "market_name": self.market_name,
            "detected_keyword": self.keyword,
            "full_text": self.full_text,
        }


class KeywordDetector:
    """Matches recognised speech text against per-market keyword lists.

    Args:
        markets: Mapping of market_id to market configuration dicts.
            Each dict should contain "keywords" (list) and optionally
            "trigger_type" ("any" or "exact") and "name" (str).
        exact_matching_override: When True, force exact matching for all
            markets regardless of their individual trigger_type setting.
    """

    def __init__(
        self,
        markets: dict[str, dict[str, Any]],
        exact_matching_override: bool = False,
    ) -> None:
        self.markets = markets
        self.exact_matching_override = exact_matching_override

    def check_text(
        self,
        text: str,
        excluded_markets: set[str] | None = None,
    ) -> list[Detection]:
        """Return all markets whose keywords are found in *text*.

        Args:
            text: Lowercased recognised utterance.
            excluded_markets: Set of market_ids to skip (already traded).

        Returns:
            List of Detection objects for each matching market.
        """
        excluded = excluded_markets or set()
        detections: list[Detection] = []
        text = text.lower()

        for market_id, market_config in self.markets.items():
            if market_id in excluded:
                continue

            keywords: list[str] = [kw.lower() for kw in market_config.get("keywords", [])]
            trigger_type: str = market_config.get("trigger_type", "any")

            if self.exact_matching_override:
                trigger_type = "exact"

            matched_keyword: str | None = None

            if trigger_type == "exact":
                if text in keywords:
                    matched_keyword = text
            else:
                for kw in keywords:
                    if kw in text:
                        matched_keyword = kw
                        break

            if matched_keyword is not None:
                detection = Detection(
                    market_id=market_id,
                    market_name=market_config.get("name", market_id),
                    keyword=matched_keyword,
                    full_text=text,
                )
                logger.info(
                    "Keyword '%s' detected for market %s", matched_keyword, market_id
                )
                detections.append(detection)

        return detections
