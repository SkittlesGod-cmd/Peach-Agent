"""Telegram bot interface for Peach."""

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
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


class PeachBot:
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
        self.logger = logger or logging.getLogger("peach.bot")

    def start(self) -> None:
        if not TELEGRAM_AVAILABLE:
            self.logger.info("python-telegram-bot not installed — Telegram bot disabled.")
            return
        if not self.config.telegram_bot_token:
            self.logger.info("No Telegram bot token configured — Telegram bot disabled.")
            return
        t = threading.Thread(target=self._run, daemon=True, name="peach-bot")
        t.start()
        self.logger.info("Telegram bot thread started.")

    # ── Proactive push methods ─────────────────────────────────────────────────

    def notify(self, message: str) -> None:
        token = self.config.telegram_bot_token
        if not token:
            return
        chat_id = self.config.telegram_chat_id or str(self.memory.get("_telegram_chat_id", ""))
        if not chat_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message[:4096]},
                timeout=10,
            )
        except Exception as exc:
            self.logger.warning("Telegram notification failed: %s", exc)

    def send_photo(self, photo_bytes: bytes, caption: str = "") -> None:
        token = self.config.telegram_bot_token
        if not token:
            return
        chat_id = self.config.telegram_chat_id or str(self.memory.get("_telegram_chat_id", ""))
        if not chat_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"photo": ("chart.png", photo_bytes, "image/png")},
                timeout=30,
            )
        except Exception as exc:
            self.logger.warning("Telegram send_photo failed: %s", exc)

    def send_document(self, doc_bytes: bytes, filename: str, caption: str = "") -> None:
        token = self.config.telegram_bot_token
        if not token:
            return
        chat_id = self.config.telegram_chat_id or str(self.memory.get("_telegram_chat_id", ""))
        if not chat_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"document": (filename, doc_bytes, "application/pdf")},
                timeout=60,
            )
        except Exception as exc:
            self.logger.warning("Telegram send_document failed: %s", exc)

    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async())
        except Exception as exc:
            self.logger.exception("Telegram bot crashed: %s", exc)

    async def _run_async(self) -> None:
        app = Application.builder().token(self.config.telegram_bot_token).build()

        app.add_handler(CommandHandler("start",       self._cmd_start))
        app.add_handler(CommandHandler("help",        self._cmd_start))
        app.add_handler(CommandHandler("briefing",    self._cmd_briefing))
        app.add_handler(CommandHandler("portfolio",   self._cmd_portfolio))
        app.add_handler(CommandHandler("add",         self._cmd_add))
        app.add_handler(CommandHandler("remove",      self._cmd_remove))
        app.add_handler(CommandHandler("quote",       self._cmd_quote))
        app.add_handler(CommandHandler("alert",       self._cmd_alert))
        app.add_handler(CommandHandler("alerts",      self._cmd_alerts))
        app.add_handler(CommandHandler("chart",       self._cmd_chart))
        app.add_handler(CommandHandler("history",     self._cmd_history))
        app.add_handler(CommandHandler("pdf",         self._cmd_pdf))
        app.add_handler(CommandHandler("technicals",  self._cmd_technicals))
        app.add_handler(CommandHandler("correlation", self._cmd_correlation))
        app.add_handler(CommandHandler("trades",      self._cmd_trades))
        app.add_handler(CommandHandler("trade",       self._cmd_trade))
        app.add_handler(CommandHandler("closetr",     self._cmd_close_trade))
        app.add_handler(CommandHandler("mychatid",    self._cmd_mychatid))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        self.logger.info("Telegram bot polling for updates.")
        await asyncio.Event().wait()

    # ── Commands ───────────────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._save_chat_id(update)
        await update.message.reply_text(
            "Peach is running.\n\n"
            "/briefing — run a morning briefing\n"
            "/pdf — generate and send PDF brief\n"
            "/chart TICKER [1mo|3mo|6mo|1y] — price chart\n"
            "/technicals TICKER — RSI, SMA, 52w levels\n"
            "/correlation — portfolio correlation heatmap\n"
            "/portfolio — tracked positions & P&L\n"
            "/add AAPL 10 150.00 — add a position\n"
            "/remove AAPL — remove a position\n"
            "/quote AAPL — live quote\n"
            "/history — portfolio value over time\n"
            "/alert AAPL above 200 — price alert\n"
            "/alerts — list active alerts\n"
            "/trade LONG AAPL 150.00 [shares] [notes] — log paper trade\n"
            "/trades — paper trade history\n"
            "/closetr ID 165.00 — close a paper trade\n"
            "/mychatid — show your chat ID\n\n"
            "Or just type anything to ask the agent."
        )

    async def _cmd_mychatid(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.message.chat_id)
        self._save_chat_id(update)
        await update.message.reply_text(
            f"Your chat ID is: {chat_id}\n"
            "Add `telegram_chat_id` to peach_config.json to receive proactive alerts."
        )

    async def _cmd_briefing(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._save_chat_id(update)
        await update.message.reply_text("Running briefing…")
        try:
            from .data_fetcher import MarketDataFetcher
            market_data = MarketDataFetcher(self.config, self.logger).fetch()
            briefing = self.agent.run_briefing(market_data)
            for chunk in _split(briefing):
                await update.message.reply_text(chunk)
        except Exception as exc:
            self.logger.exception("On-demand briefing failed: %s", exc)
            await update.message.reply_text(f"Briefing failed: {exc}")

    async def _cmd_pdf(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._save_chat_id(update)
        await update.message.reply_text("Generating PDF brief…")
        try:
            from .charts import ChartGenerator
            from .data_fetcher import MarketDataFetcher
            from .report import ReportGenerator

            market_data = MarketDataFetcher(self.config, self.logger).fetch()
            briefing = self.agent.run_briefing(market_data)
            cg = ChartGenerator(self.logger)
            positions = self.portfolio.get_all_positions()
            chart_images: dict[str, bytes] = {}
            if positions:
                try:
                    chart_images["Portfolio P&L"] = cg.portfolio_pnl_chart(positions)
                except Exception:
                    pass
            pdf_bytes = ReportGenerator().morning_brief(
                briefing, market_data.macro, positions, chart_images
            )
            await update.message.reply_document(
                document=io.BytesIO(pdf_bytes),
                filename=f"peach_brief_{date.today()}.pdf",
                caption="Morning Brief",
            )
        except Exception as exc:
            self.logger.exception("PDF generation failed: %s", exc)
            await update.message.reply_text(f"PDF failed: {exc}")

    async def _cmd_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        if not args:
            await update.message.reply_text(
                "Usage:\n"
                "  /chart AAPL [1mo|3mo|6mo|1y]  — candlestick\n"
                "  /chart AAPL MSFT NVDA [3mo]    — comparison"
            )
            return

        # Detect period token: last arg if it matches a period pattern
        period_tokens = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y"}
        period = "3mo" if len(args) > 1 and args[-1].lower() in period_tokens else "1mo"
        tickers = [a.upper() for a in args if a.lower() not in period_tokens]

        if not tickers:
            await update.message.reply_text("Please specify at least one ticker.")
            return

        from .charts import ChartGenerator
        cg = ChartGenerator(self.logger)

        if len(tickers) == 1:
            await update.message.reply_text(f"Generating chart for {tickers[0]}…")
            try:
                img = cg.price_chart(tickers[0], period)
                await update.message.reply_photo(photo=img, caption=f"{tickers[0]}  ·  {period}")
            except Exception as exc:
                await update.message.reply_text(f"Chart failed: {exc}")
        else:
            label = "  ·  ".join(tickers)
            await update.message.reply_text(f"Generating comparison for {label}…")
            try:
                img = cg.comparison_chart(tickers, period)
                await update.message.reply_photo(photo=img, caption=f"Return comparison  ·  {period}")
            except Exception as exc:
                await update.message.reply_text(f"Comparison chart failed: {exc}")

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        snapshots = self.portfolio.get_snapshots(days=90)
        if len(snapshots) < 2:
            await update.message.reply_text(
                "Not enough history yet — snapshots are recorded at 4 PM ET each trading day. "
                "Check back after the first two market closes."
            )
            return
        try:
            from .charts import ChartGenerator
            img = ChartGenerator(self.logger).portfolio_history_chart(snapshots)
            latest = snapshots[-1]
            pnl = latest["pnl"]
            caption = (
                f"Portfolio value  ·  {len(snapshots)} days\n"
                f"Current: ${latest['total_value']:,.0f}  |  P&L: ${pnl:+,.0f}"
            )
            await update.message.reply_photo(photo=img, caption=caption)
        except Exception as exc:
            await update.message.reply_text(f"History chart failed: {exc}")

    async def _cmd_technicals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /technicals TICKER")
            return
        result = self.agent.executor.execute("get_technicals", {"ticker": args[0]})
        await update.message.reply_text(result)

    async def _cmd_correlation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        positions = self.portfolio.get_all_positions()
        if len(positions) < 2:
            await update.message.reply_text("Need at least 2 portfolio positions for correlation.")
            return
        await update.message.reply_text("Computing correlation…")
        try:
            from .charts import ChartGenerator
            img = ChartGenerator(self.logger).correlation_heatmap(
                [p.ticker for p in positions], period="3mo"
            )
            await update.message.reply_photo(photo=img, caption="30-day return correlation")
        except Exception as exc:
            await update.message.reply_text(f"Correlation failed: {exc}")

    async def _cmd_portfolio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._save_chat_id(update)
        positions = self.portfolio.get_all_positions()
        if not positions:
            await update.message.reply_text("No positions. Use /add TICKER SHARES COST_BASIS")
            return
        lines = ["Portfolio:"]
        for pos in positions:
            lines.append(f"• {pos.ticker}: {pos.shares} sh @ ${pos.cost_basis:.2f}")
            if pos.thesis:
                lines.append(f"  {pos.thesis}")
        await update.message.reply_text("\n".join(lines))

    async def _cmd_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        if len(args) < 3:
            await update.message.reply_text("Usage: /add TICKER SHARES COST_BASIS [thesis]")
            return
        try:
            ticker = args[0].upper()
            shares = float(args[1])
            cost = float(args[2])
            thesis = " ".join(args[3:])
            self.portfolio.add_position(ticker, shares, cost, thesis)
            await update.message.reply_text(f"Added {shares} shares of {ticker} @ ${cost:.2f}.")
        except ValueError as exc:
            await update.message.reply_text(f"Error: {exc}")

    async def _cmd_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /remove TICKER")
            return
        ticker = args[0].upper()
        if self.portfolio.remove_position(ticker):
            await update.message.reply_text(f"Removed {ticker} from portfolio.")
        else:
            await update.message.reply_text(f"{ticker} not found in portfolio.")

    async def _cmd_quote(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /quote TICKER")
            return
        result = self.agent.executor.execute("get_quote", {"ticker": args[0]})
        await update.message.reply_text(result)

    async def _cmd_alert(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        if len(args) < 3:
            await update.message.reply_text("Usage: /alert TICKER above|below PRICE [note]")
            return
        try:
            ticker = args[0].upper()
            direction = args[1].lower()
            if direction not in ("above", "below"):
                await update.message.reply_text("Direction must be 'above' or 'below'.")
                return
            price = float(args[2])
            note = " ".join(args[3:])
            result = self.agent.executor.execute(
                "add_alert", {"ticker": ticker, "direction": direction, "price": price, "note": note}
            )
            await update.message.reply_text(result)
        except ValueError as exc:
            await update.message.reply_text(f"Error: {exc}")

    async def _cmd_alerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        alerts = self.portfolio.get_active_alerts()
        if not alerts:
            await update.message.reply_text("No active alerts.")
            return
        lines = ["Active alerts:"]
        for a in alerts:
            lines.append(f"• #{a.id} {a.ticker} {a.direction} ${a.price:.2f}")
            if a.note:
                lines.append(f"  {a.note}")
        await update.message.reply_text("\n".join(lines))

    async def _cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        trades = self.portfolio.get_paper_trades()
        if not trades:
            await update.message.reply_text(
                "No paper trades. Log one with:\n"
                "/trade LONG AAPL 150.00 [shares] [notes]"
            )
            return
        lines = ["Paper trades (latest 20):"]
        for t in trades[:20]:
            status = "OPEN" if t.is_open else f"CLOSED @ ${t.exit_price:.2f}"
            pnl_str = f"  P&L: ${t.pnl:+.2f}" if t.pnl is not None else ""
            lines.append(f"#{t.id} {t.ticker} {t.direction.upper()} {t.shares}sh"
                         f" @ ${t.entry_price:.2f}  [{status}]{pnl_str}")
            if t.notes:
                lines.append(f"  {t.notes}")
        await update.message.reply_text("\n".join(lines))

    async def _cmd_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # /trade LONG AAPL 150.00 [SHARES] [notes...]
        args = context.args or []
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: /trade LONG|SHORT TICKER ENTRY_PRICE [SHARES] [notes]"
            )
            return
        try:
            raw_dir = args[0].lower()
            direction = "long" if raw_dir in ("long", "buy") else "short"
            ticker = args[1].upper()
            entry = float(args[2])
            shares = 1.0
            notes = ""
            if len(args) > 3:
                try:
                    shares = float(args[3])
                    notes = " ".join(args[4:])
                except ValueError:
                    notes = " ".join(args[3:])
            trade_id = self.portfolio.add_paper_trade(ticker, direction, entry, shares, notes)
            await update.message.reply_text(
                f"Paper trade #{trade_id}: {direction.upper()} {shares}sh {ticker} @ ${entry:.2f}"
            )
        except ValueError as exc:
            await update.message.reply_text(f"Error: {exc}")

    async def _cmd_close_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # /closetr ID EXIT_PRICE
        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text("Usage: /closetr TRADE_ID EXIT_PRICE")
            return
        try:
            trade_id = int(args[0])
            exit_price = float(args[1])
            result = self.portfolio.close_paper_trade(trade_id, exit_price)
            await update.message.reply_text(result)
        except ValueError as exc:
            await update.message.reply_text(f"Error: {exc}")

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._save_chat_id(update)
        text = (update.message.text or "").strip()
        if not text:
            return
        try:
            reply = self.agent.chat(text)
            for chunk in _split(reply):
                await update.message.reply_text(chunk)
        except Exception as exc:
            self.logger.exception("Chat response failed: %s", exc)
            await update.message.reply_text(f"Error: {exc}")

    def _save_chat_id(self, update: Update) -> None:
        chat_id = str(update.message.chat_id)
        if self.memory.get("_telegram_chat_id") != chat_id:
            self.memory.set("_telegram_chat_id", chat_id)


def _split(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
