"""Agentic reasoning loop with tool use for Peach."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .config import PeachConfig
from .data_fetcher import AggregatedMarketData
from .memory import AgentMemory
from .portfolio import PortfolioLedger
from .tools import TOOL_SCHEMAS, ToolExecutor


SYSTEM_PROMPT = """You are Peach, a pre-market intelligence agent for an active trader.

You have tools to fetch live quotes, portfolio P&L, pre-market data, news, and set alerts.
Use them when they add value. Be concise and cite specific numbers — never invent prices or facts.

When writing a morning briefing, structure it as:
1. **Macro Tape** — index levels and overnight moves
2. **Portfolio Check** — open positions vs current levels
3. **Standouts** — unusual price/volume moves from the watchlist
4. **Lookout List** — 2-3 tickers worth watching today with specific reasons
5. **Risk Notes** — what could go wrong

When answering a direct question, answer directly and briefly.
Always make uncertainty explicit if data is stale or unavailable.
"""


class PeachAgent:
    def __init__(
        self,
        config: PeachConfig,
        portfolio: PortfolioLedger,
        memory: AgentMemory,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.portfolio = portfolio
        self.memory = memory
        self.logger = logger or logging.getLogger("peach")
        self.executor = ToolExecutor(config, portfolio, logger)
        self.session = requests.Session()

    def run_briefing(self, market_data: AggregatedMarketData) -> str:
        """Run the morning briefing agentic loop. Falls back to MarketAnalyzer on failure."""
        try:
            return self._run_loop(self._briefing_prompt(market_data))
        except Exception as exc:
            self.logger.warning("Agent loop failed; falling back to MarketAnalyzer: %s", exc)
            from .analyzer import MarketAnalyzer
            return MarketAnalyzer(self.config, self.logger).analyze(market_data)

    def chat(self, message: str) -> str:
        """Respond to a free-text user message with tool access."""
        context = self.memory.context_summary()
        content = f"{context}\n\nUser: {message}" if context else message
        return self._run_loop(content)

    # ------------------------------------------------------------------ #

    def _briefing_prompt(self, market_data: AggregatedMarketData) -> str:
        payload = market_data.to_prompt_payload()
        parts = []
        context = self.memory.context_summary()
        if context:
            parts.append(context)
        parts.append("Generate the morning market briefing. Use your tools for live data if helpful.")
        parts.append(f"Pre-fetched market snapshot:\n{json.dumps(payload, indent=2)}")
        return "\n\n".join(parts)

    def _run_loop(self, user_content: str, max_iterations: int = 8) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        for _ in range(max_iterations):
            response = self._call_llm(messages)
            choice = response.get("choices", [{}])[0]
            msg = choice.get("message", {})
            finish = choice.get("finish_reason", "stop")

            messages.append(msg)

            if finish == "tool_calls" and msg.get("tool_calls"):
                for call in msg["tool_calls"]:
                    fn = call["function"]
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    result = self.executor.execute(fn["name"], args)
                    self.logger.debug("Tool %s → %s", fn["name"], result[:200])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result,
                    })
                continue

            return str(msg.get("content", "")).strip()

        return "Analysis timed out after maximum tool iterations."

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        response = self.session.post(
            self.config.proxy_url,
            json={
                "model": self.config.openrouter_model,
                "temperature": 0.2,
                "messages": messages,
                "tools": TOOL_SCHEMAS,
                "tool_choice": "auto",
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()
