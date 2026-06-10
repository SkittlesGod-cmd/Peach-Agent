"""Market data and news aggregation for Peach."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Callable, TypeVar
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import yfinance as yf

from .config import PeachConfig


# ── Sentiment word sets ────────────────────────────────────────────────────────

_BULLISH = {
    "beat", "beats", "surge", "surges", "surged", "record", "upgrade", "upgraded",
    "buy", "bullish", "rally", "rallies", "rallied", "gain", "gains", "up", "rise",
    "rises", "rose", "high", "strong", "growth", "profit", "profits", "exceed",
    "exceeds", "exceeded", "positive", "outperform", "breakout", "momentum",
}
_BEARISH = {
    "miss", "misses", "missed", "decline", "declines", "declined", "cut", "cuts",
    "downgrade", "downgraded", "sell", "bearish", "drop", "drops", "dropped",
    "loss", "losses", "down", "fall", "falls", "fell", "low", "weak", "warning",
    "concern", "concerns", "risk", "risks", "crash", "recession", "disappoint",
    "disappoints", "disappointing",
}


def _score_sentiment(text: str) -> str:
    words = set(text.lower().split())
    bull = len(words & _BULLISH)
    bear = len(words & _BEARISH)
    if bull > bear + 1:
        return "bullish"
    if bear > bull + 1:
        return "bearish"
    return "neutral"


def _calc_rsi(closes: pd.Series, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    lg, ll = gain.iloc[-1], loss.iloc[-1]
    if ll == 0:
        return 100.0
    return round(100 - (100 / (1 + lg / ll)), 1)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StockMetric:
    ticker: str
    close: float | None
    previous_close: float | None
    volume: int | None
    percent_change: float | None
    trade_date: str | None
    pre_market_price: float | None = None
    pre_market_change_pct: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    rsi_14: float | None = None
    above_sma20: bool | None = None
    above_sma50: bool | None = None
    earnings_date: str | None = None
    news_sentiment: str | None = None
    source: str = "yfinance"


@dataclass(frozen=True)
class NewsHeadline:
    title: str
    url: str
    source: str
    published_at: str | None
    summary: str | None = None


@dataclass(frozen=True)
class AggregatedMarketData:
    fetched_at: str
    tickers: list[str]
    metrics: list[StockMetric]
    headlines: list[NewsHeadline]
    macro: dict = field(default_factory=dict)

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "tickers": self.tickers,
            "macro": self.macro,
            "metrics": [asdict(metric) for metric in self.metrics],
            "headlines": [asdict(headline) for headline in self.headlines],
        }


# ── Fetcher ────────────────────────────────────────────────────────────────────

_T = TypeVar("_T")
_YF_TIMEOUT = 12  # seconds — curl_cffi has no built-in cap; enforce one here


def _yf_get(fn: Callable[[], _T], default: _T, timeout: int = _YF_TIMEOUT) -> _T:
    """Run a yfinance call in a thread with a hard wall-clock timeout."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout)
        except (FutureTimeout, Exception):
            return default


_MACRO_SYMBOLS = {
    "VIX":       "^VIX",
    "YIELD_10Y": "^TNX",
    "DXY":       "DX-Y.NYB",
}


class MarketDataFetcher:
    def __init__(self, config: PeachConfig, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("peach")
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "PeachMarketBriefing/1.0 (local AI assistant; contact=local-user)"}
        )

    def fetch(self) -> AggregatedMarketData:
        macro = self._fetch_macro()
        metrics = self.fetch_previous_day_metrics(self.config.tickers)
        headlines = self.fetch_headlines(self.config.tickers, self.config.headline_limit)
        metrics = self._enrich_sentiment(metrics, headlines)
        return AggregatedMarketData(
            fetched_at=datetime.now(timezone.utc).isoformat(),
            tickers=self.config.tickers,
            metrics=metrics,
            headlines=headlines,
            macro=macro,
        )

    # ── Macro ──────────────────────────────────────────────────────────────────

    def _fetch_macro(self) -> dict[str, Any]:
        macro: dict[str, Any] = {}
        for name, symbol in _MACRO_SYMBOLS.items():
            try:
                info = _yf_get(lambda s=symbol: yf.Ticker(s).info, default={})
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
                if price:
                    macro[name] = {
                        "price": round(float(price), 4),
                        "change_pct": round((float(price) - float(prev)) / float(prev) * 100, 2)
                        if prev else None,
                    }
            except Exception as exc:
                self.logger.debug("Macro fetch failed for %s: %s", symbol, exc)
        return macro

    # ── Stock metrics ──────────────────────────────────────────────────────────

    def fetch_previous_day_metrics(self, tickers: list[str]) -> list[StockMetric]:
        metrics: list[StockMetric] = []
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                # 3 months for RSI(14) and SMA(50)
                history = _yf_get(
                    lambda _t=t: _t.history(period="3mo", interval="1d", auto_adjust=False),
                    default=pd.DataFrame(),
                )
                if history.empty:
                    self.logger.warning("No yfinance history returned for %s", ticker)
                    metrics.append(self._empty_metric(ticker))
                    continue

                history = history.dropna(subset=["Close"])
                closes = history["Close"].astype(float)
                latest_close = float(closes.iloc[-1])
                previous_close = float(closes.iloc[-2]) if len(closes) >= 2 else None
                percent_change = (
                    (latest_close - previous_close) / previous_close * 100
                    if previous_close and previous_close != 0 else None
                )

                trade_date = history.index[-1]
                trade_date_value = (
                    trade_date.date().isoformat() if hasattr(trade_date, "date") else str(trade_date)
                )

                # Technicals
                rsi = _calc_rsi(closes)
                sma20 = closes.rolling(20).mean().iloc[-1] if len(closes) >= 20 else None
                sma50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
                above_sma20 = bool(latest_close > float(sma20)) if sma20 is not None else None
                above_sma50 = bool(latest_close > float(sma50)) if sma50 is not None else None

                # Info (52w H/L, pre-market, earnings)
                info = _yf_get(lambda _t=t: _t.info, default={})
                week_52_high = info.get("fiftyTwoWeekHigh")
                week_52_low = info.get("fiftyTwoWeekLow")

                pre_market_price: float | None = None
                pre_market_change_pct: float | None = None
                try:
                    pm = info.get("preMarketPrice")
                    pm_pct = info.get("preMarketChangePercent")
                    if pm is not None:
                        pre_market_price = round(float(pm), 4)
                    if pm_pct is not None:
                        pre_market_change_pct = round(float(pm_pct) * 100, 4)
                except Exception:
                    pass

                earnings_date: str | None = None
                try:
                    ts = info.get("earningsTimestamp")
                    if ts:
                        earnings_date = datetime.fromtimestamp(int(ts)).date().isoformat()
                except Exception:
                    pass

                vol = history.iloc[-1].get("Volume") if "Volume" in history.columns else None

                metrics.append(StockMetric(
                    ticker=ticker,
                    close=round(latest_close, 4),
                    previous_close=round(previous_close, 4) if previous_close is not None else None,
                    volume=int(vol) if vol is not None and pd.notna(vol) else None,
                    percent_change=round(percent_change, 4) if percent_change is not None else None,
                    trade_date=trade_date_value,
                    pre_market_price=pre_market_price,
                    pre_market_change_pct=pre_market_change_pct,
                    week_52_high=round(float(week_52_high), 4) if week_52_high else None,
                    week_52_low=round(float(week_52_low), 4) if week_52_low else None,
                    rsi_14=rsi,
                    above_sma20=above_sma20,
                    above_sma50=above_sma50,
                    earnings_date=earnings_date,
                ))
            except Exception as exc:
                self.logger.exception("Failed to fetch metrics for %s: %s", ticker, exc)
                metrics.append(self._empty_metric(ticker))
        return metrics

    def _empty_metric(self, ticker: str) -> StockMetric:
        return StockMetric(
            ticker=ticker, close=None, previous_close=None, volume=None,
            percent_change=None, trade_date=None,
        )

    def _enrich_sentiment(
        self, metrics: list[StockMetric], headlines: list[NewsHeadline]
    ) -> list[StockMetric]:
        from dataclasses import replace
        enriched = []
        for m in metrics:
            text = " ".join(
                (h.title or "") + " " + (h.summary or "")
                for h in headlines
                if m.ticker.lower() in (h.title or "").lower()
                or m.ticker.lower() in (h.summary or "").lower()
            ).strip()
            sentiment = _score_sentiment(text) if text else None
            enriched.append(replace(m, news_sentiment=sentiment))
        return enriched

    # ── Headlines ──────────────────────────────────────────────────────────────

    def fetch_headlines(self, tickers: list[str], limit: int = 10) -> list[NewsHeadline]:
        fetchers = [
            self._fetch_alpha_vantage_news,
            self._fetch_newsapi_news,
            self._fetch_yahoo_rss_news,
        ]
        seen_urls: set[str] = set()
        headlines: list[NewsHeadline] = []
        for fetcher in fetchers:
            try:
                for headline in fetcher(tickers, limit):
                    if not headline.url or headline.url in seen_urls:
                        continue
                    seen_urls.add(headline.url)
                    headlines.append(headline)
                    if len(headlines) >= limit:
                        return headlines
            except Exception as exc:
                self.logger.exception("Headline fetcher %s failed: %s", fetcher.__name__, exc)
        return headlines[:limit]

    def _fetch_alpha_vantage_news(self, tickers: list[str], limit: int) -> list[NewsHeadline]:
        if not self.config.alpha_vantage_api_key:
            return []
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ",".join(tickers),
            "limit": str(limit),
            "sort": "LATEST",
            "apikey": self.config.alpha_vantage_api_key,
        }
        response = self.session.get(url, params=params, timeout=20)
        response.raise_for_status()
        feed = response.json().get("feed", [])
        headlines = []
        for item in feed[:limit]:
            headlines.append(NewsHeadline(
                title=str(item.get("title", "")).strip(),
                url=str(item.get("url", "")).strip(),
                source=str(item.get("source", "Alpha Vantage")).strip(),
                published_at=str(item.get("time_published", "")).strip() or None,
                summary=str(item.get("summary", "")).strip() or None,
            ))
        return [h for h in headlines if h.title and h.url]

    def _fetch_newsapi_news(self, tickers: list[str], limit: int) -> list[NewsHeadline]:
        if not self.config.news_api_key:
            return []
        query = " OR ".join(tickers[:8]) + " OR stock market OR Federal Reserve OR earnings"
        response = self.session.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": limit,
                "apiKey": self.config.news_api_key,
            },
            timeout=20,
        )
        response.raise_for_status()
        articles = response.json().get("articles", [])
        headlines = []
        for item in articles[:limit]:
            source = item.get("source") or {}
            headlines.append(NewsHeadline(
                title=str(item.get("title", "")).strip(),
                url=str(item.get("url", "")).strip(),
                source=str(source.get("name", "NewsAPI")).strip(),
                published_at=str(item.get("publishedAt", "")).strip() or None,
                summary=str(item.get("description", "")).strip() or None,
            ))
        return [h for h in headlines if h.title and h.url]

    def _fetch_yahoo_rss_news(self, tickers: list[str], limit: int) -> list[NewsHeadline]:
        symbols = ",".join(tickers[:12])
        url = (
            "https://feeds.finance.yahoo.com/rss/2.0/headline"
            f"?s={quote_plus(symbols)}&region=US&lang=en-US"
        )
        response = self.session.get(url, timeout=20)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        headlines = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title and link:
                headlines.append(NewsHeadline(
                    title=title,
                    url=link,
                    source="Yahoo Finance",
                    published_at=(item.findtext("pubDate") or "").strip() or None,
                    summary=(item.findtext("description") or "").strip() or None,
                ))
        return headlines
