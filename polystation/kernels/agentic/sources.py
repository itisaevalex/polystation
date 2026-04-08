"""Data source plugins for the agentic kernel — news, market data, social, YouTube."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class DataSource(ABC):
    """Base class for data sources that feed context to the agentic kernel."""

    name: str = "unknown"

    @abstractmethod
    async def fetch(self) -> str:
        """Fetch data and return it as a text string for LLM context."""
        ...


class MarketDataSource(DataSource):
    """Fetches current market prices and order book data."""

    name = "market_data"

    def __init__(self, engine: Any, symbols: list[str] | None = None) -> None:
        self.engine = engine
        self.symbols = symbols or []

    async def fetch(self) -> str:
        if not self.engine.market_data:
            return "Market data unavailable."

        lines = ["=== Current Market Data ==="]
        for sym in self.symbols[:10]:
            mid = self.engine.market_data.get_midpoint(sym)
            if mid is not None:
                lines.append(f"  {sym[:30]}... midpoint: {mid:.4f}")

        if self.engine.portfolio:
            s = self.engine.portfolio.get_summary()
            lines.append(f"\nPortfolio: {s.get('position_count', 0)} positions, "
                         f"P&L: ${s.get('total_pnl', 0):.2f}")

        return "\n".join(lines)


class NewsSource(DataSource):
    """Fetches news headlines from an RSS or API endpoint."""

    name = "news"

    def __init__(self, feed_url: str = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN",
                 max_items: int = 10) -> None:
        self.feed_url = feed_url
        self.max_items = max_items

    async def fetch(self) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.feed_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()

            articles = data.get("Data", data) if isinstance(data, dict) else data
            if not isinstance(articles, list):
                return "No news available."

            lines = ["=== Recent News ==="]
            for article in articles[:self.max_items]:
                title = article.get("title", article.get("headline", ""))
                if title:
                    lines.append(f"  - {title}")

            return "\n".join(lines)
        except Exception as exc:
            logger.warning("News fetch failed: %s", exc)
            return f"News unavailable: {exc}"


class YouTubeTranscriptSource(DataSource):
    """Extracts transcript from a YouTube video for context."""

    name = "youtube_transcript"

    def __init__(self, video_url: str = "") -> None:
        self.video_url = video_url

    async def fetch(self) -> str:
        if not self.video_url:
            return "No YouTube video URL configured."

        try:
            # Use yt-dlp to get video info (title, description)
            import asyncio
            import subprocess

            result = await asyncio.to_thread(
                subprocess.run,
                ["yt-dlp", "--get-title", "--get-description", self.video_url],
                capture_output=True, text=True, timeout=30,
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                # Truncate to reasonable size for LLM context
                if len(output) > 3000:
                    output = output[:3000] + "\n... (truncated)"
                return f"=== YouTube Video ===\n{output}"
            return f"Failed to fetch video: {result.stderr[:200]}"
        except Exception as exc:
            return f"YouTube fetch failed: {exc}"


class CustomAPISource(DataSource):
    """Fetches data from a custom API endpoint."""

    name = "custom_api"

    def __init__(self, url: str, headers: dict[str, str] | None = None,
                 label: str = "Custom Data") -> None:
        self.url = url
        self.headers = headers or {}
        self.label = label

    async def fetch(self) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, headers=self.headers,
                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    text = await resp.text()
                    if len(text) > 3000:
                        text = text[:3000] + "\n... (truncated)"
                    return f"=== {self.label} ===\n{text}"
        except Exception as exc:
            return f"{self.label} unavailable: {exc}"
