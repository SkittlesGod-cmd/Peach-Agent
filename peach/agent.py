"""Agentic reasoning loop with tool use for Peach."""

from __future__ import annotations

from datetime import date
import json
import logging
import time
from typing import Any

import requests

from .config import PeachConfig
from .data_fetcher import AggregatedMarketData
from .memory import AgentMemory
from .portfolio import PortfolioLedger
from .tools import TOOL_SCHEMAS, ToolExecutor


SYSTEM_PROMPT = """You are Peach, a pre-market intelligence agent for an active trader.

Tools available: get_quote, get_portfolio, get_pre_market, get_news, add_alert,
get_technicals, get_earnings_calendar, get_correlation, search_web.

Use tools proactively when they add real value. Cite specific numbers — never invent prices or facts.

## REQUIRED OUTPUT FORMAT for morning briefings

Your response MUST begin exactly like this template (fill in real values):

# Peach Brief — {Weekday Mon DD}

> {RISK-ON|RISK-OFF|MIXED} — {one tight sentence explaining the tape}

---

Then continue with these sections in order, each separated by `---`:

**Macro Tape**
| Index | Price | Change |
|-------|-------|--------|
| SPY   | $XXX  | ↑/↓ X.X% |
| QQQ   | $XXX  | ↑/↓ X.X% |
| DIA   | $XXX  | ↑/↓ X.X% |

VIX XX.X ↑/↓ (+X.X%) · 10Y X.XX% · DXY XX.X

---

**Portfolio Check**
Call get_portfolio. For each position show: price vs cost, unrealised P&L %.
Mark positions ≥5% in drawdown with `▼`. Skip section if portfolio is empty.

---

**Earnings Watch**
Call get_earnings_calendar. Flag any earnings in the next 7 days.
If none: _No earnings this week for watched tickers._

---

**Standouts**
2-4 bullets. Use ⚠ oversold when RSI < 30, ⚠ overbought when RSI > 70.

---

**Lookout List**
2-3 rows. Format: `**TICKER** · Long/Short · $XXX level · one-sentence rationale`

---

**Risk Notes**
2-3 concise bullets.

---

**Today's Focus** — {single most important thing to watch today}

## End of format template

When answering a direct question (not a briefing), be brief and precise. State uncertainty explicitly.
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
            raw = self._run_loop(self._briefing_prompt(market_data))
            briefing = self._polish(raw)
            self._auto_update_memory(briefing, market_data)
            return briefing
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
        today = date.today().strftime("%a %b %d").replace(" 0", " ")
        parts = []
        context = self.memory.context_summary()
        if context:
            parts.append(context)
        parts.append(
            f"Today is {today}. Generate the morning market briefing.\n\n"
            "IMPORTANT — you MUST call these tools before writing their sections:\n"
            "1. Call get_portfolio FIRST — write exactly what it returns; "
            "do NOT invent cost bases. If empty, write '_No positions tracked._'\n"
            "2. Call get_earnings_calendar — write only what the tool reports; "
            "do NOT add tickers from training data.\n\n"
            "Use the pre-fetched snapshot for everything else."
        )
        parts.append(f"Pre-fetched market snapshot:\n{json.dumps(payload, indent=2)}")
        return "\n\n".join(parts)

    def _polish(self, text: str) -> str:
        """Guarantee the date header and Today's Focus are present."""
        today = date.today().strftime("%a %b %d").replace(" 0", " ")
        header = f"# Peach Brief — {today}"
        lines = text.splitlines()

        # Prepend header if not present
        if not lines or not lines[0].startswith("# Peach Brief"):
            text = f"{header}\n\n{text}"
            lines = text.splitlines()

        # Append Today's Focus if not present
        if "**Today's Focus**" not in text:
            text = text.rstrip() + "\n\n---\n\n**Today's Focus** — Watch the key support levels and VIX direction at the open."

        return text

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

    def _auto_update_memory(self, briefing: str, market_data: AggregatedMarketData) -> None:
        """Persist a rolling context summary after each briefing."""
        try:
            from datetime import date
            self.memory.set("_last_briefing_date", date.today().isoformat())
            self.memory.set("_last_briefing_summary", briefing[:600])
            positions = self.portfolio.get_all_positions()
            if positions:
                self.memory.set(
                    "portfolio_context",
                    ", ".join(f"{p.ticker}@${p.cost_basis:.0f}" for p in positions),
                )
            top = sorted(
                [m for m in market_data.metrics if m.percent_change is not None],
                key=lambda m: abs(m.percent_change or 0),
                reverse=True,
            )[:3]
            if top:
                self.memory.set(
                    "recent_movers",
                    ", ".join(f"{m.ticker} {m.percent_change:+.1f}%" for m in top),
                )
        except Exception as exc:
            self.logger.debug("Memory auto-update failed: %s", exc)

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
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
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    wait = 2 ** attempt * 2  # 2s, 4s
                    self.logger.warning("LLM call failed (attempt %d/3): %s — retrying in %ds",
                                        attempt + 1, exc, wait)
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]
