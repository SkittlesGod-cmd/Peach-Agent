"""Discord bot integration for Peach."""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from datetime import date
from typing import TYPE_CHECKING

import requests

from .config import PeachConfig
from .memory import AgentMemory
from .portfolio import PortfolioLedger

if TYPE_CHECKING:
    from .agent import PeachAgent

try:
    import discord
    from discord.ext import commands as dc_commands
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False


class PeachDiscord:
    def __init__(
        self,
        config: PeachConfig,
        agent: "PeachAgent",
        portfolio: PortfolioLedger,
        memory: AgentMemory,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.agent = agent
        self.portfolio = portfolio
        self.memory = memory
        self.logger = logger or logging.getLogger("peach.discord")

    def start(self) -> None:
        if not DISCORD_AVAILABLE:
            self.logger.info("discord.py not installed — Discord bot disabled.")
            return
        if not self.config.discord_token:
            self.logger.info("No Discord token configured — Discord bot disabled.")
            return
        t = threading.Thread(target=self._run, daemon=True, name="peach-discord")
        t.start()
        self.logger.info("Discord bot thread started.")

    def notify(self, message: str) -> None:
        if not self.config.discord_token or not self.config.discord_channel_id:
            return
        try:
            requests.post(
                f"https://discord.com/api/v10/channels/{self.config.discord_channel_id}/messages",
                headers={
                    "Authorization": f"Bot {self.config.discord_token}",
                    "Content-Type": "application/json",
                },
                json={"content": message[:2000]},
                timeout=10,
            )
        except Exception as exc:
            self.logger.warning("Discord notification failed: %s", exc)

    def send_file(self, file_bytes: bytes, filename: str, content: str = "") -> None:
        if not self.config.discord_token or not self.config.discord_channel_id:
            return
        try:
            requests.post(
                f"https://discord.com/api/v10/channels/{self.config.discord_channel_id}/messages",
                headers={"Authorization": f"Bot {self.config.discord_token}"},
                data={"content": content},
                files={"file": (filename, file_bytes)},
                timeout=30,
            )
        except Exception as exc:
            self.logger.warning("Discord send_file failed: %s", exc)

    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async())
        except Exception as exc:
            self.logger.exception("Discord bot crashed: %s", exc)

    async def _run_async(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        bot = dc_commands.Bot(command_prefix="!", intents=intents, help_command=None)

        @bot.event
        async def on_ready() -> None:
            self.logger.info("Discord bot connected as %s", bot.user)

        @bot.command(name="help")
        async def cmd_help(ctx: dc_commands.Context) -> None:
            await ctx.send(
                "**Peach commands**\n"
                "`!briefing` — run a briefing now\n"
                "`!quote TICKER` — live quote\n"
                "`!portfolio` — open positions with live P&L\n"
                "`!add TICKER SHARES COST` — track a position\n"
                "`!alert TICKER above|below PRICE` — set a price alert\n"
                "`!chart TICKER [period]` — price chart (1mo/3mo/6mo/1y)\n"
                "`!technicals TICKER` — RSI, SMA, 52w levels\n"
                "`!trade LONG|SHORT TICKER PRICE [SHARES] [note]` — open a paper trade\n"
                "`!trades` — list open paper trades\n"
                "`!closetr ID PRICE` — close a paper trade\n"
                "`!peach <question>` — ask the agent anything"
            )

        @bot.command(name="briefing")
        async def cmd_briefing(ctx: dc_commands.Context) -> None:
            await ctx.send("Running briefing…")
            try:
                from .data_fetcher import MarketDataFetcher
                market_data = MarketDataFetcher(self.config, self.logger).fetch()
                briefing = self.agent.run_briefing(market_data)
                for chunk in _split(briefing, 1900):
                    await ctx.send(chunk)
            except Exception as exc:
                self.logger.exception("Discord briefing failed: %s", exc)
                await ctx.send(f"Briefing failed: {exc}")

        @bot.command(name="quote")
        async def cmd_quote(ctx: dc_commands.Context, ticker: str = "") -> None:
            if not ticker:
                await ctx.send("Usage: `!quote TICKER`")
                return
            result = self.agent.executor.execute("get_quote", {"ticker": ticker})
            await ctx.send(result)

        @bot.command(name="portfolio")
        async def cmd_portfolio(ctx: dc_commands.Context) -> None:
            result = self.agent.executor.execute("get_portfolio", {})
            await ctx.send(result)

        @bot.command(name="add")
        async def cmd_add(
            ctx: dc_commands.Context,
            ticker: str = "",
            shares: str = "",
            cost: str = "",
            *,
            thesis: str = "",
        ) -> None:
            if not ticker or not shares or not cost:
                await ctx.send("Usage: `!add TICKER SHARES COST [thesis]`")
                return
            try:
                self.portfolio.add_position(
                    ticker.upper(), float(shares), float(cost), thesis
                )
                await ctx.send(
                    f"Added **{ticker.upper()}** — {shares} sh @ ${float(cost):.2f}"
                    + (f"\nThesis: {thesis}" if thesis else "")
                )
            except ValueError:
                await ctx.send("Invalid number. Usage: `!add TICKER SHARES COST`")

        @bot.command(name="alert")
        async def cmd_alert(
            ctx: dc_commands.Context,
            ticker: str = "",
            direction: str = "",
            price: str = "",
            *,
            note: str = "",
        ) -> None:
            if not ticker or direction not in ("above", "below") or not price:
                await ctx.send("Usage: `!alert TICKER above|below PRICE [note]`")
                return
            try:
                result = self.agent.executor.execute(
                    "add_alert",
                    {"ticker": ticker, "direction": direction, "price": float(price), "note": note},
                )
                await ctx.send(result)
            except ValueError:
                await ctx.send("Invalid price. Usage: `!alert TICKER above|below PRICE`")

        @bot.command(name="chart")
        async def cmd_chart(
            ctx: dc_commands.Context, ticker: str = "", period: str = "1mo"
        ) -> None:
            if not ticker:
                await ctx.send("Usage: `!chart TICKER [1mo|3mo|6mo|1y]`")
                return
            await ctx.send(f"Generating chart for **{ticker.upper()}**…")
            try:
                from .charts import ChartGenerator
                img = ChartGenerator(self.logger).price_chart(ticker.upper(), period)
                await ctx.send(
                    file=discord.File(io.BytesIO(img), filename=f"{ticker.upper()}.png")
                )
            except Exception as exc:
                await ctx.send(f"Chart failed: {exc}")

        @bot.command(name="technicals")
        async def cmd_technicals(ctx: dc_commands.Context, ticker: str = "") -> None:
            if not ticker:
                await ctx.send("Usage: `!technicals TICKER`")
                return
            result = self.agent.executor.execute("get_technicals", {"ticker": ticker})
            await ctx.send(f"```\n{result}\n```")

        @bot.command(name="trade")
        async def cmd_trade(
            ctx: dc_commands.Context,
            direction: str = "",
            ticker: str = "",
            price: str = "",
            shares: str = "1",
            *,
            note: str = "",
        ) -> None:
            if direction.upper() not in ("LONG", "SHORT") or not ticker or not price:
                await ctx.send("Usage: `!trade LONG|SHORT TICKER PRICE [SHARES] [note]`")
                return
            try:
                trade_id = self.portfolio.add_paper_trade(
                    ticker.upper(),
                    direction.lower(),
                    float(price),
                    float(shares),
                    note,
                )
                await ctx.send(
                    f"Paper trade #{trade_id} opened: **{direction.upper()} {ticker.upper()}** "
                    f"@ ${float(price):.2f}  ×{float(shares):.0f}"
                    + (f"\n_{note}_" if note else "")
                )
            except ValueError:
                await ctx.send("Invalid price/shares. Usage: `!trade LONG|SHORT TICKER PRICE [SHARES]`")

        @bot.command(name="trades")
        async def cmd_trades(ctx: dc_commands.Context) -> None:
            open_trades = self.portfolio.get_paper_trades(open_only=True)
            if not open_trades:
                await ctx.send("No open paper trades. Use `!trade LONG|SHORT TICKER PRICE` to open one.")
                return
            lines = ["**Open Paper Trades**"]
            for t in open_trades:
                lines.append(
                    f"`#{t.id}` **{t.direction.upper()} {t.ticker}** "
                    f"@ ${t.entry_price:.2f} × {t.shares:.0f}  ·  {t.entry_date}"
                    + (f"\n   _{t.notes}_" if t.notes else "")
                )
            await ctx.send("\n".join(lines))

        @bot.command(name="closetr")
        async def cmd_closetr(
            ctx: dc_commands.Context, trade_id: str = "", exit_price: str = ""
        ) -> None:
            if not trade_id or not exit_price:
                await ctx.send("Usage: `!closetr TRADE_ID EXIT_PRICE`")
                return
            try:
                result = self.portfolio.close_paper_trade(int(trade_id), float(exit_price))
                await ctx.send(result)
            except ValueError:
                await ctx.send("Invalid ID or price. Usage: `!closetr ID PRICE`")

        @bot.command(name="peach")
        async def cmd_peach(ctx: dc_commands.Context, *, message: str = "") -> None:
            if not message:
                await ctx.send("Ask me anything about the markets — `!peach what's happening with NVDA?`")
                return
            try:
                reply = self.agent.chat(message)
                for chunk in _split(reply, 1900):
                    await ctx.send(chunk)
            except Exception as exc:
                await ctx.send(f"Error: {exc}")

        await bot.start(self.config.discord_token)


def _split(text: str, limit: int = 1900) -> list[str]:
    """Split text at newline boundaries, never mid-line."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > limit and current_lines:
            chunks.append("".join(current_lines))
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += len(line)
    if current_lines:
        chunks.append("".join(current_lines))
    return chunks
