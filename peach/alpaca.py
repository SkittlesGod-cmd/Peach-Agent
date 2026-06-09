"""Read-only Alpaca brokerage client."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .config import PeachConfig


class AlpacaClient:
    PAPER_URL = "https://paper-api.alpaca.markets"
    LIVE_URL  = "https://api.alpaca.markets"

    def __init__(self, config: PeachConfig, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("peach")
        self.base = self.PAPER_URL if config.alpaca_paper else self.LIVE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID":     config.alpaca_api_key or "",
            "APCA-API-SECRET-KEY": config.alpaca_secret_key or "",
        })

    def is_configured(self) -> bool:
        return bool(self.config.alpaca_api_key and self.config.alpaca_secret_key)

    def get_account(self) -> dict[str, Any]:
        return self._get("/v2/account")

    def get_positions(self) -> list[dict[str, Any]]:
        result = self._get("/v2/positions")
        return result if isinstance(result, list) else []

    def get_orders(self, limit: int = 10) -> list[dict[str, Any]]:
        result = self._get("/v2/orders", params={
            "status": "all", "limit": limit, "direction": "desc"
        })
        return result if isinstance(result, list) else []

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self.session.get(f"{self.base}{path}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ── Formatted helpers used by tool executor ── #

    def account_summary(self) -> str:
        acct = self.get_account()
        equity     = float(acct.get("equity",       0))
        cash       = float(acct.get("cash",          0))
        buying_pw  = float(acct.get("buying_power",  0))
        last_eq    = float(acct.get("last_equity",   equity))
        day_pl     = equity - last_eq
        day_pct    = (day_pl / last_eq * 100) if last_eq else 0.0
        env        = "paper" if self.config.alpaca_paper else "live"
        return (
            f"Alpaca account ({env}): "
            f"equity ${equity:,.2f} | cash ${cash:,.2f} | "
            f"buying power ${buying_pw:,.2f} | "
            f"today P&L ${day_pl:+,.2f} ({day_pct:+.2f}%)"
        )

    def positions_summary(self) -> str:
        positions = self.get_positions()
        if not positions:
            return "No open positions in Alpaca account."
        lines = [f"Alpaca positions ({'paper' if self.config.alpaca_paper else 'live'}):"]
        for pos in positions:
            sym        = pos.get("symbol", "?")
            qty        = float(pos.get("qty", 0))
            avg_entry  = float(pos.get("avg_entry_price", 0))
            current    = float(pos.get("current_price",   0))
            unreal_pl  = float(pos.get("unrealized_pl",   0))
            unreal_pct = float(pos.get("unrealized_plpc", 0)) * 100
            day_pl     = float(pos.get("unrealized_intraday_pl", 0))
            lines.append(
                f"  {sym}: {qty} sh @ ${avg_entry:.2f} | "
                f"now ${current:.2f} | "
                f"total P&L ${unreal_pl:+.0f} ({unreal_pct:+.1f}%) | "
                f"today ${day_pl:+.0f}"
            )
        return "\n".join(lines)
