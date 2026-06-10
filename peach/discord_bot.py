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
                "`!portfolio` — open positions\n"
                "`!chart TICKER [period]` — price chart (1mo/3mo/6mo/1y)\n"
                "`!technicals TICKER` — RSI, SMA, 52w levels\n"
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
            positions = self.portfolio.get_all_positions()
            if not positions:
                await ctx.send("No positions tracked. Use `!add TICKER SHARES COST` to add positions.")
                return
            lines = ["**Portfolio**"]
            for pos in positions:
                lines.append(f"• **{pos.ticker}** — {pos.shares} sh @ ${pos.cost_basis:.2f}")
            await ctx.send("\n".join(lines))

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
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
