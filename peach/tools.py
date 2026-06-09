"""Tool schemas and executors for the Peach agentic loop."""

from __future__ import annotations

import logging
from typing import Any

import yfinance as yf

from .config import PeachConfig
from .portfolio import PortfolioLedger


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "Get the current price and day change for a ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "e.g. AAPL, SPY, NVDA"}
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": "Get all open portfolio positions with cost basis and current P&L.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pre_market",
            "description": (
                "Get pre-market price and change for a ticker. "
                "Only meaningful before 9:30 AM ET on trading days."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"}
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Get recent news headlines for a specific ticker from yfinance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"}
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_alert",
            "description": "Set a price alert. Peach will notify you when the price crosses the threshold.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker":    {"type": "string"},
                    "direction": {"type": "string", "enum": ["above", "below"]},
                    "price":     {"type": "number"},
                    "note":      {"type": "string", "description": "Optional reason for the alert"},
                },
                "required": ["ticker", "direction", "price"],
            },
        },
    },
]


class ToolExecutor:
    def __init__(
        self,
        config: PeachConfig,
        portfolio: PortfolioLedger,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.portfolio = portfolio
        self.logger = logger or logging.getLogger("peach")

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "get_quote":
                return self._get_quote(arguments["ticker"])
            if name == "get_portfolio":
                return self._get_portfolio()
            if name == "get_pre_market":
                return self._get_pre_market(arguments["ticker"])
            if name == "get_news":
                return self._get_news(arguments["ticker"])
            if name == "add_alert":
                return self._add_alert(
                    arguments["ticker"],
                    arguments["direction"],
                    float(arguments["price"]),
                    arguments.get("note", ""),
                )
            return f"Unknown tool: {name}"
        except Exception as exc:
            self.logger.warning("Tool %s raised: %s", name, exc)
            return f"Tool error: {exc}"

    # ------------------------------------------------------------------ #

    def _get_quote(self, ticker: str) -> str:
        ticker = ticker.upper()
        info = yf.Ticker(ticker).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
        volume = info.get("volume") or info.get("regularMarketVolume")
        if not price:
            return f"No price data for {ticker}."
        parts = [f"{ticker}: ${price:.2f}"]
        if prev:
            chg = price - prev
            pct = chg / prev * 100
            parts.append(f"{chg:+.2f} ({pct:+.2f}%)")
        if volume:
            parts.append(f"vol {volume:,}")
        return " | ".join(parts)

    def _get_portfolio(self) -> str:
        positions = self.portfolio.get_all_positions()
        if not positions:
            return "Portfolio is empty. Use /add TICKER SHARES COST to add positions."
        lines = ["Portfolio:"]
        for pos in positions:
            info = yf.Ticker(pos.ticker).info
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            if current:
                pnl = (current - pos.cost_basis) * pos.shares
                pnl_pct = (current - pos.cost_basis) / pos.cost_basis * 100
                lines.append(
                    f"  {pos.ticker}: {pos.shares} sh @ ${pos.cost_basis:.2f} | "
                    f"now ${current:.2f} | P&L ${pnl:+.0f} ({pnl_pct:+.1f}%)"
                )
            else:
                lines.append(f"  {pos.ticker}: {pos.shares} sh @ ${pos.cost_basis:.2f} (no live price)")
            if pos.thesis:
                lines.append(f"    thesis: {pos.thesis}")
        return "\n".join(lines)

    def _get_pre_market(self, ticker: str) -> str:
        ticker = ticker.upper()
        info = yf.Ticker(ticker).info
        pre_price = info.get("preMarketPrice")
        pre_change = info.get("preMarketChangePercent")
        if not pre_price:
            return f"No pre-market data for {ticker} (market may be open or data unavailable)."
        pct_str = f" ({pre_change * 100:+.2f}%)" if pre_change else ""
        return f"{ticker} pre-market: ${pre_price:.2f}{pct_str}"

    def _get_news(self, ticker: str) -> str:
        ticker = ticker.upper()
        news = yf.Ticker(ticker).news or []
        if not news:
            return f"No recent news found for {ticker}."
        lines = [f"News for {ticker}:"]
        for item in news[:6]:
            title = item.get("title", "")
            if title:
                lines.append(f"  - {title}")
        return "\n".join(lines)

    def _add_alert(self, ticker: str, direction: str, price: float, note: str) -> str:
        alert_id = self.portfolio.add_alert(ticker.upper(), direction, price, note)
        return f"Alert #{alert_id} set: notify when {ticker.upper()} {direction} ${price:.2f}."

