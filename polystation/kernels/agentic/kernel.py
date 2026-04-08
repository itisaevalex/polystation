"""Agentic trading kernel — LLM-powered trading decisions from custom data sources."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, TYPE_CHECKING

from polystation.core.kernel import Kernel
from polystation.kernels import register
from polystation.kernels.agentic.llm import LLMClient
from polystation.kernels.agentic.sources import DataSource, MarketDataSource, NewsSource

if TYPE_CHECKING:
    from polystation.core.engine import TradingEngine

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are a quantitative trading analyst. You analyze market data and news to generate trading decisions.

You must respond in JSON with this exact structure:
{
    "action": "BUY" | "SELL" | "HOLD",
    "symbol": "<token_id or symbol to trade>",
    "size": <number of shares/contracts>,
    "confidence": <0.0 to 1.0>,
    "reasoning": "<brief explanation>"
}

Rules:
- Only recommend BUY or SELL when confidence > 0.6
- Recommend HOLD when uncertain
- Size should be proportional to confidence (higher confidence = larger size)
- Base size is 50 units; scale up to 200 for high-confidence trades
- Consider risk: don't recommend buying if portfolio is already heavily exposed
"""


@register
class AgenticKernel(Kernel):
    """LLM-powered trading kernel that analyzes data sources and generates trades.

    The decision loop:
    1. Gather context from all configured data sources
    2. Send context + system prompt to the LLM
    3. Parse the structured JSON response
    4. Execute the trade decision if confidence is above threshold

    Parameters:
        exchange_name: Which exchange to trade on (default: polymarket).
        system_prompt: Custom trading thesis/strategy for the LLM.
        model: LLM model to use (default: claude-sonnet-4-20250514).
        provider: LLM provider — "anthropic" or "openai".
        decision_interval: Seconds between LLM analysis cycles.
        min_confidence: Minimum confidence threshold to execute a trade.
        max_position_usd: Maximum position size in USD.
        symbols: List of symbols/token_ids to monitor and trade.
        news_enabled: Whether to include news in the context.
    """

    name = "agentic"

    def __init__(
        self,
        exchange_name: str = "polymarket",
        system_prompt: str = "",
        model: str = "claude-sonnet-4-20250514",
        provider: str = "anthropic",
        api_key: str | None = None,
        decision_interval: float = 300.0,
        min_confidence: float = 0.6,
        max_position_usd: float = 100.0,
        symbols: list[str] | None = None,
        news_enabled: bool = True,
    ) -> None:
        super().__init__()
        self.exchange_name = exchange_name
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.model = model
        self.provider = provider
        self.api_key = api_key
        self.decision_interval = decision_interval
        self.min_confidence = min_confidence
        self.max_position_usd = max_position_usd
        self.symbols = symbols or []
        self.news_enabled = news_enabled

        self._llm: LLMClient | None = None
        self._sources: list[DataSource] = []
        self._task: asyncio.Task | None = None
        self._decisions: list[dict[str, Any]] = []
        self._cycle_count: int = 0

    async def start(self) -> None:
        """Initialize LLM client, data sources, and start the decision loop."""
        self._llm = LLMClient(provider=self.provider, model=self.model, api_key=self.api_key)

        if not self._llm.available:
            logger.warning("AgenticKernel: LLM not available — will run in analysis-only mode")

        # Set up data sources
        self._sources = []
        if self.engine:
            self._sources.append(MarketDataSource(self.engine, self.symbols))
        if self.news_enabled:
            self._sources.append(NewsSource())

        self._task = asyncio.create_task(self._decision_loop())
        logger.info("AgenticKernel started: model=%s interval=%.0fs symbols=%d",
                     self.model, self.decision_interval, len(self.symbols))

    async def stop(self) -> None:
        """Stop the decision loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AgenticKernel stopped after %d cycles, %d decisions",
                     self._cycle_count, len(self._decisions))

    async def _decision_loop(self) -> None:
        """Main loop: gather data → analyze with LLM → execute decisions."""
        while True:
            try:
                await self._run_cycle()
                self._cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AgenticKernel cycle error")
            await asyncio.sleep(self.decision_interval)

    async def _run_cycle(self) -> None:
        """Single decision cycle."""
        # 1. Gather context from all data sources
        context = await self._gather_context()

        if not self._llm or not self._llm.available:
            logger.debug("AgenticKernel: No LLM — skipping analysis")
            return

        # 2. Analyze with LLM
        decision = await self._llm.structured_analyze(
            self.system_prompt, context, max_tokens=512
        )

        logger.info("AgenticKernel decision: %s", json.dumps(decision)[:200])
        self._decisions.append(decision)
        if len(self._decisions) > 100:
            self._decisions = self._decisions[-100:]

        # 3. Execute if confidence is high enough
        if decision.get("parse_error"):
            logger.warning("AgenticKernel: LLM response was not valid JSON")
            return

        await self._execute_decision(decision)

    async def _gather_context(self) -> str:
        """Collect data from all configured sources into a single context string."""
        parts: list[str] = []
        for source in self._sources:
            try:
                data = await source.fetch()
                if data:
                    parts.append(data)
            except Exception as exc:
                parts.append(f"[{source.name} error: {exc}]")

        return "\n\n".join(parts)

    async def _execute_decision(self, decision: dict[str, Any]) -> None:
        """Convert an LLM decision to an order and submit it."""
        action = decision.get("action", "HOLD").upper()
        if action == "HOLD":
            return

        confidence = float(decision.get("confidence", 0))
        if confidence < self.min_confidence:
            logger.debug("AgenticKernel: confidence %.2f below threshold %.2f — skipping",
                         confidence, self.min_confidence)
            return

        symbol = decision.get("symbol", "")
        if not symbol and self.symbols:
            symbol = self.symbols[0]

        if not symbol:
            logger.warning("AgenticKernel: no symbol in decision — skipping")
            return

        size = float(decision.get("size", 50))
        price = 0.0

        # Get current price from exchange or market data
        if self.engine and self.engine.market_data:
            mid = self.engine.market_data.get_midpoint(symbol)
            if mid:
                price = mid

        if price <= 0:
            logger.warning("AgenticKernel: no price available for %s — skipping", symbol[:20])
            return

        # Cap position value
        if price * size > self.max_position_usd:
            size = self.max_position_usd / price

        # Submit order
        if self.engine and self.engine.orders and self.engine.execution:
            order = self.engine.orders.create_order(
                token_id=symbol,
                side=action,
                price=price,
                size=size,
                kernel_name=self.name,
            )
            result = await self.engine.execution.submit_order(order)
            logger.info("AgenticKernel trade: %s %s %.0f @ %.4f (confidence=%.2f) → %s",
                         action, symbol[:20], size, price, confidence,
                         "OK" if result else "FAILED")

    def add_source(self, source: DataSource) -> None:
        """Add a custom data source."""
        self._sources.append(source)

    def get_status(self) -> dict[str, Any]:
        base = super().get_status()
        base.update({
            "exchange_name": self.exchange_name,
            "model": self.model,
            "provider": self.provider,
            "llm_available": self._llm.available if self._llm else False,
            "decision_interval": self.decision_interval,
            "min_confidence": self.min_confidence,
            "max_position_usd": self.max_position_usd,
            "symbols": self.symbols,
            "sources": [s.name for s in self._sources],
            "cycle_count": self._cycle_count,
            "total_decisions": len(self._decisions),
            "recent_decisions": self._decisions[-5:],
        })
        return base
