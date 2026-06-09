"""Tool schemas and executors for the Peach agentic loop."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from .config import PeachConfig
from .data_fetcher import _calc_rsi
from .portfolio import PortfolioLedger


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "Get the current price, day change, and volume for a ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "e.g. AAPL, SPY, NVDA"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": "Get all open portfolio positions with cost basis and live unrealized P&L.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pre_market",
            "description": "Get pre-market price and change for a ticker (before 9:30 AM ET).",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "Get recent news headlines for a specific ticker from Yahoo Finance.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_alert",
            "description": "Set a price alert. Peach notifies when price crosses the threshold.",
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
    {
        "type": "function",
        "function": {
            "name": "get_technicals",
            "description": (
                "Get technical indicators for a ticker: RSI(14), SMA(20), SMA(50), "
                "52-week high/low, and distance from each level. Use to identify "
                "overbought/oversold conditions and trend direction."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_earnings_calendar",
            "description": "List tickers in the watchlist with earnings reports in the next 7 days.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_correlation",
            "description": (
                "Get the 30-day return correlation matrix for all portfolio holdings. "
                "Useful for understanding concentration risk."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the web for recent news, analyst notes, or any market information "
                "not covered by other tools. Use for specific events, earnings reactions, "
                "or macro developments."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
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
            if name == "get_technicals":
                return self._get_technicals(arguments["ticker"])
            if name == "get_earnings_calendar":
                return self._get_earnings_calendar()
            if name == "get_correlation":
                return self._get_correlation()
            if name == "search_web":
                return self._search_web(arguments["query"])
            return f"Unknown tool: {name}"
        except Exception as exc:
            self.logger.warning("Tool %s raised: %s", name, exc)
            return f"Tool error: {exc}"

    # ── Market data ────────────────────────────────────────────────────────────

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

    # ── Technicals ─────────────────────────────────────────────────────────────

    def _get_technicals(self, ticker: str) -> str:
        ticker = ticker.upper()
        history = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=False)
        if history.empty:
            return f"No data for {ticker}."
        closes = history["Close"].astype(float)
        current = float(closes.iloc[-1])

        rsi = _calc_rsi(closes)
        sma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
        sma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None

        info = yf.Ticker(ticker).info
        high52 = info.get("fiftyTwoWeekHigh")
        low52 = info.get("fiftyTwoWeekLow")

        parts = [f"{ticker} technicals — ${current:.2f}"]
        if rsi is not None:
            tag = " 🔴 oversold" if rsi < 30 else (" 🟡 overbought" if rsi > 70 else "")
            parts.append(f"  RSI(14): {rsi:.1f}{tag}")
        if sma20:
            rel = "above" if current > sma20 else "below"
            parts.append(f"  SMA20:  ${sma20:.2f}  (price {rel})")
        if sma50:
            rel = "above" if current > sma50 else "below"
            parts.append(f"  SMA50:  ${sma50:.2f}  (price {rel})")
        if high52:
            pct = (current - high52) / high52 * 100
            parts.append(f"  52w High: ${high52:.2f}  ({pct:+.1f}% from high)")
        if low52:
            pct = (current - low52) / low52 * 100
            parts.append(f"  52w Low:  ${low52:.2f}  ({pct:+.1f}% from low)")
        return "\n".join(parts)

    # ── Earnings calendar ──────────────────────────────────────────────────────

    def _get_earnings_calendar(self) -> str:
        today = date.today()
        cutoff = today + timedelta(days=7)
        upcoming = []
        for ticker in self.config.tickers:
            try:
                info = yf.Ticker(ticker).info
                ts = info.get("earningsTimestamp")
                if ts:
                    ed = datetime.fromtimestamp(int(ts)).date()
                    if today <= ed <= cutoff:
                        upcoming.append(f"{ticker} — {ed.strftime('%b %d')}")
            except Exception:
                continue
        if not upcoming:
            return "No earnings in the next 7 days for watched tickers."
        return "Earnings in next 7 days:\n" + "\n".join(f"  • {u}" for u in upcoming)

    # ── Correlation ────────────────────────────────────────────────────────────

    def _get_correlation(self) -> str:
        positions = self.portfolio.get_all_positions()
        if len(positions) < 2:
            return "Need at least 2 portfolio positions to compute correlation."
        tickers = [p.ticker for p in positions]
        try:
            raw = yf.download(tickers, period="1mo", interval="1d",
                              auto_adjust=True, progress=False)
            close = raw["Close"] if "Close" in raw.columns else raw
            if isinstance(close, pd.Series):
                close = close.to_frame(name=tickers[0])
            corr = close.pct_change().dropna().corr().round(2)
            lines = ["30-day return correlation:"]
            cols = list(corr.columns)
            for i, row in enumerate(cols):
                for col in cols[i + 1 :]:
                    lines.append(f"  {row}/{col}: {corr.loc[row, col]:.2f}")
            return "\n".join(lines) if len(lines) > 1 else "Insufficient data."
        except Exception as exc:
            return f"Correlation failed: {exc}"

    # ── Web search ─────────────────────────────────────────────────────────────

    def _search_web(self, query: str) -> str:
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    title = r.get("title", "")
                    body = (r.get("body", "") or "")[:200]
                    results.append(f"• {title}: {body}")
            return "\n".join(results) if results else "No results found."
        except ImportError:
            return "Web search unavailable. Run: pip install duckduckgo-search"
        except Exception as exc:
            return f"Search failed: {exc}"
