"""LLM client wrapper — supports Anthropic Claude and OpenAI."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Try importing LLM providers (both optional)
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class LLMClient:
    """Unified LLM interface for trading analysis.

    Supports Anthropic Claude (preferred) and OpenAI as fallback.
    Returns structured JSON responses for trade decisions.
    """

    def __init__(self, provider: str = "anthropic",
                 model: str = "claude-sonnet-4-20250514",
                 api_key: str | None = None) -> None:
        self.provider = provider
        self.model = model
        self._client: Any = None

        if provider == "anthropic" and ANTHROPIC_AVAILABLE:
            self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
            logger.info("LLMClient initialized: Anthropic (%s)", model)
        elif provider == "openai" and OPENAI_AVAILABLE:
            self._client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()
            logger.info("LLMClient initialized: OpenAI (%s)", model)
        else:
            logger.warning("LLMClient: %s not available. Install the SDK.", provider)

    @property
    def available(self) -> bool:
        return self._client is not None

    async def analyze(self, system_prompt: str, user_message: str,
                      max_tokens: int = 1024) -> str:
        """Send a message and return the response text."""
        if not self._client:
            return '{"error": "LLM client not available"}'

        try:
            if self.provider == "anthropic":
                import asyncio
                resp = await asyncio.to_thread(
                    self._client.messages.create,
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                return resp.content[0].text

            elif self.provider == "openai":
                import asyncio
                resp = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content or ""

        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            return json.dumps({"error": str(exc)})

        return '{"error": "Unknown provider"}'

    async def structured_analyze(self, system_prompt: str, user_message: str,
                                  max_tokens: int = 1024) -> dict[str, Any]:
        """Get a structured JSON response from the LLM.

        The system prompt should instruct the model to respond in JSON.
        """
        raw = await self.analyze(system_prompt, user_message, max_tokens)

        # Try to parse JSON from the response
        try:
            # Handle markdown code blocks
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            return json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            logger.warning("Failed to parse LLM response as JSON: %s", raw[:200])
            return {"raw_response": raw, "parse_error": True}
