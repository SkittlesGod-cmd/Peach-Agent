"""Market data and news aggregation for Peach."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import requests
import yfinance as yf

from .config import PeachConfig


@dataclass(frozen=True)
class StockMetric:
    ticker: str
    close: float | None
    previous_close: float | None
    volume: int | None
    percent_change: float | None
    trade_date: str | None
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

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "tickers": self.tickers,
            "metrics": [metric.__dict__ for metric in self.metrics],
            "headlines": [headline.__dict__ for headline in self.headlines],
        }


class MarketDataFetcher:
    def __init__(self, config: PeachConfig, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("peach")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "PeachMarketBriefing/1.0 "
                    "(local AI assistant; contact=local-user)"
                )
            }
        )

    def fetch(self) -> AggregatedMarketData:
        metrics = self.fetch_previous_day_metrics(self.config.tickers)
        headlines = self.fetch_headlines(self.config.tickers, self.config.headline_limit)
        return AggregatedMarketData(
            fetched_at=datetime.now(UTC).isoformat(),
            tickers=self.config.tickers,
            metrics=metrics,
            headlines=headlines,
        )

    def fetch_previous_day_metrics(self, tickers: list[str]) -> list[StockMetric]:
        metrics: list[StockMetric] = []
        for ticker in tickers:
            try:
                history = yf.Ticker(ticker).history(period="10d", interval="1d", auto_adjust=False)
                if history.empty:
                    self.logger.warning("No yfinance history returned for %s", ticker)
                    metrics.append(
                        StockMetric(
                            ticker=ticker,
                            close=None,
                            previous_close=None,
                            volume=None,
                            percent_change=None,
                            trade_date=None,
                        )
                    )
                    continue

                history = history.dropna(subset=["Close"])
                latest = history.iloc[-1]
                previous = history.iloc[-2] if len(history) >= 2 else None
                latest_close = float(latest["Close"])
                previous_close = float(previous["Close"]) if previous is not None else None
                percent_change = None
                if previous_close and previous_close != 0:
                    percent_change = ((latest_close - previous_close) / previous_close) * 100

                trade_date = history.index[-1]
                if hasattr(trade_date, "date"):
                    trade_date_value = trade_date.date().isoformat()
                else:
                    trade_date_value = str(trade_date)

                metrics.append(
                    StockMetric(
                        ticker=ticker,
                        close=round(latest_close, 4),
                        previous_close=round(previous_close, 4) if previous_close is not None else None,
                        volume=int(latest["Volume"]) if "Volume" in latest and not latest.isna()["Volume"] else None,
                        percent_change=round(percent_change, 4) if percent_change is not None else None,
                        trade_date=trade_date_value,
                    )
                )
            except Exception as exc:
                self.logger.exception("Failed to fetch yfinance metrics for %s: %s", ticker, exc)
                metrics.append(
                    StockMetric(
                        ticker=ticker,
                        close=None,
                        previous_close=None,
                        volume=None,
                        percent_change=None,
                        trade_date=None,
                    )
                )
        return metrics

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
        payload = response.json()
        feed = payload.get("feed", [])
        headlines: list[NewsHeadline] = []
        for item in feed[:limit]:
            headlines.append(
                NewsHeadline(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    source=str(item.get("source", "Alpha Vantage")).strip(),
                    published_at=str(item.get("time_published", "")).strip() or None,
                    summary=str(item.get("summary", "")).strip() or None,
                )
            )
        return [headline for headline in headlines if headline.title and headline.url]

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
        payload = response.json()
        articles = payload.get("articles", [])
        headlines: list[NewsHeadline] = []
        for item in articles[:limit]:
            source = item.get("source") or {}
            headlines.append(
                NewsHeadline(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    source=str(source.get("name", "NewsAPI")).strip(),
                    published_at=str(item.get("publishedAt", "")).strip() or None,
                    summary=str(item.get("description", "")).strip() or None,
                )
            )
        return [headline for headline in headlines if headline.title and headline.url]

    def _fetch_yahoo_rss_news(self, tickers: list[str], limit: int) -> list[NewsHeadline]:
        symbols = ",".join(tickers[:12])
        url = (
            "https://feeds.finance.yahoo.com/rss/2.0/headline"
            f"?s={quote_plus(symbols)}&region=US&lang=en-US"
        )
        response = self.session.get(url, timeout=20)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        headlines: list[NewsHeadline] = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            published_at = (item.findtext("pubDate") or "").strip() or None
            summary = (item.findtext("description") or "").strip() or None
            if title and link:
                headlines.append(
                    NewsHeadline(
                        title=title,
                        url=link,
                        source="Yahoo Finance",
                        published_at=published_at,
                        summary=summary,
                    )
                )
        return headlines
