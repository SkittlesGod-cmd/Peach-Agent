"""Thread-safe TTL cache for yfinance API responses.

The agent tool loop can call get_quote, get_technicals, etc. on the same ticker
multiple times in one iteration. Without caching, each call hits yfinance and
risks rate limiting. Responses are cached for 60 seconds (300 for OHLCV history).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

_store: dict[str, tuple[datetime, Any]] = {}
_lock = threading.Lock()

_INFO_TTL    = 60   # seconds — quote / info
_HISTORY_TTL = 300  # 5 min   — OHLCV history


def get(key: str, fetch: Callable[[], Any], ttl: int = _INFO_TTL) -> Any:
    with _lock:
        if key in _store:
            ts, data = _store[key]
            if datetime.now() - ts < timedelta(seconds=ttl):
                return data
    data = fetch()
    with _lock:
        _store[key] = (datetime.now(), data)
    return data


def ticker_info(ticker: str) -> dict[str, Any]:
    import yfinance as yf
    return get(f"info:{ticker}", lambda: yf.Ticker(ticker).info)


def ticker_history(ticker: str, period: str = "3mo", interval: str = "1d") -> Any:
    import yfinance as yf
    return get(
        f"hist:{ticker}:{period}:{interval}",
        lambda: yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False),
        ttl=_HISTORY_TTL,
    )


def clear() -> None:
    with _lock:
        _store.clear()
