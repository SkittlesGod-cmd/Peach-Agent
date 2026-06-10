"""Background scheduler daemon for Peach."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from pathlib import Path
import signal
import sys
from zoneinfo import ZoneInfo

from .config import PeachConfig, load_config
from .logging_setup import configure_logging


def run_pipeline(
    config: PeachConfig,
    logger: logging.Logger,
    agent: object,
    discord_bot: object,
    portfolio: object,
    chart_gen: object,
) -> None:
    logger.info("Starting Peach pipeline for tickers: %s", ", ".join(config.tickers))
    try:
        from .data_fetcher import MarketDataFetcher
        from .notifier import EmailNotifier
        from .agent import PeachAgent

        market_data = MarketDataFetcher(config, logger).fetch()
        logger.info("Fetched %d metrics, %d headlines, macro=%s",
                    len(market_data.metrics), len(market_data.headlines),
                    list(market_data.macro.keys()))

        briefing: str
        if isinstance(agent, PeachAgent):
            briefing = agent.run_briefing(market_data)
        else:
            from .analyzer import MarketAnalyzer
            briefing = MarketAnalyzer(config, logger).analyze(market_data)

        EmailNotifier(config, logger).send(briefing)

        # Discord: send full briefing split across messages
        from .discord_bot import _split
        for i, chunk in enumerate(_split(briefing)):
            prefix = "**Morning Briefing**\n" if i == 0 else ""
            _notify_discord(discord_bot, prefix + chunk, logger)

        # Generate charts and PDF
        from .charts import ChartGenerator
        from .report import ReportGenerator
        from .portfolio import PortfolioLedger

        positions = portfolio.get_all_positions() if isinstance(portfolio, PortfolioLedger) else []
        cg = chart_gen if isinstance(chart_gen, ChartGenerator) else ChartGenerator(logger)

        chart_images: dict[str, bytes] = {}
        if positions:
            try:
                chart_images["Portfolio P&L"] = cg.portfolio_pnl_chart(positions)
                logger.info("Portfolio P&L chart generated")
            except Exception as exc:
                logger.warning("Portfolio chart failed: %s", exc)
            try:
                chart_images["Sector Allocation"] = cg.sector_allocation_chart(positions)
                logger.info("Sector chart generated")
            except Exception as exc:
                logger.warning("Sector chart failed: %s", exc)

        try:
            pdf_bytes = ReportGenerator().morning_brief(
                briefing, market_data.macro, positions, chart_images
            )
            pdf_name = f"peach_brief_{datetime.today().date()}.pdf"
            pdf_path = config.home / "morning_brief.pdf"
            pdf_path.write_bytes(pdf_bytes)
            logger.info("Morning brief PDF written to %s", pdf_path)

            _send_discord_file(discord_bot, pdf_bytes, pdf_name, "Morning Brief", logger)
        except Exception as exc:
            logger.warning("PDF generation failed: %s", exc)

        logger.info("Peach pipeline completed successfully.")

    except Exception as exc:
        logger.exception("Peach pipeline failed: %s", exc)


def check_alerts(
    config: PeachConfig,
    logger: logging.Logger,
    portfolio: object,
    discord_bot: object,
    memory: object,
) -> None:
    try:
        import yfinance as yf
        from .portfolio import PortfolioLedger
        from .memory import AgentMemory

        if not isinstance(portfolio, PortfolioLedger):
            return

        # ── Price alerts ──────────────────────────────────────────────────────
        for alert in portfolio.get_active_alerts():
            try:
                info = yf.Ticker(alert.ticker).info
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                if not price:
                    continue
                fired = (
                    (alert.direction == "above" and price >= alert.price)
                    or (alert.direction == "below" and price <= alert.price)
                )
                if fired:
                    portfolio.mark_alert_fired(alert.id)
                    msg = (
                        f"Alert fired: {alert.ticker} is {alert.direction} "
                        f"${alert.price:.2f} (now ${price:.2f})"
                    )
                    if alert.note:
                        msg += f"\n{alert.note}"
                    logger.info(msg)
                    _notify_discord(discord_bot, msg, logger)
            except Exception as exc:
                logger.warning("Alert check failed for %s: %s", alert.ticker, exc)

        # ── Drawdown alerts ───────────────────────────────────────────────────
        threshold = config.drawdown_alert_pct
        drawdowns = portfolio.check_drawdowns(threshold)
        for ticker, cost_basis, current, pct in drawdowns:
            # Rate-limit: fire once per 24 hours per ticker
            if isinstance(memory, AgentMemory):
                key = f"_drawdown_fired_{ticker}"
                last = memory.get(key)
                if last:
                    try:
                        from datetime import timedelta
                        fired_at = datetime.fromisoformat(str(last))
                        if datetime.now() - fired_at < timedelta(hours=24):
                            continue
                    except Exception:
                        pass
                memory.set(key, datetime.now().isoformat())

            msg = (
                f"Drawdown alert: {ticker} is {pct * 100:.1f}% below cost "
                f"(${cost_basis:.2f} → ${current:.2f})"
            )
            logger.info(msg)
            _notify_discord(discord_bot, msg, logger)

    except Exception as exc:
        logger.exception("Alert checker crashed: %s", exc)


def record_portfolio_snapshot(
    config: PeachConfig,
    logger: logging.Logger,
    portfolio: object,
) -> None:
    """Daily 4 PM job: snapshot current portfolio value to SQLite."""
    from .portfolio import PortfolioLedger
    if not isinstance(portfolio, PortfolioLedger):
        return
    try:
        result = portfolio.record_snapshot()
        if result:
            logger.info("Portfolio snapshot: %s", result)
    except Exception as exc:
        logger.warning("Portfolio snapshot failed: %s", exc)


def run_correlation_report(
    config: PeachConfig,
    logger: logging.Logger,
    portfolio: object,
    discord_bot: object,
) -> None:
    """Weekly Monday job: send correlation heatmap for portfolio holdings."""
    from .portfolio import PortfolioLedger

    if not isinstance(portfolio, PortfolioLedger):
        return
    positions = portfolio.get_all_positions()
    if len(positions) < 2:
        return

    try:
        from .charts import ChartGenerator
        img = ChartGenerator(logger).correlation_heatmap(
            [p.ticker for p in positions], period="3mo"
        )
        caption = "Weekly correlation heatmap  ·  3-month returns"
        _send_discord_file(discord_bot, img, "correlation.png", caption, logger)
        logger.info("Correlation report sent.")
    except Exception as exc:
        logger.warning("Correlation report failed: %s", exc)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _notify_discord(discord_bot: object, message: str, logger: logging.Logger) -> None:
    try:
        from .discord_bot import PeachDiscord
        if isinstance(discord_bot, PeachDiscord):
            discord_bot.notify(message)
    except Exception as exc:
        logger.debug("Discord notify skipped: %s", exc)


def _send_discord_file(
    discord_bot: object, data: bytes, filename: str, content: str, logger: logging.Logger
) -> None:
    try:
        from .discord_bot import PeachDiscord
        if isinstance(discord_bot, PeachDiscord):
            discord_bot.send_file(data, filename, content)
    except Exception as exc:
        logger.debug("Discord send_file skipped: %s", exc)


def write_pid(pid_path: Path) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid(pid_path: Path, logger: logging.Logger) -> None:
    try:
        if pid_path.exists():
            existing = pid_path.read_text(encoding="utf-8").strip()
            if existing == str(os.getpid()):
                pid_path.unlink()
    except OSError as exc:
        logger.warning("Could not remove pid file %s: %s", pid_path, exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Peach background daemon.")
    parser.add_argument("--home", help="Peach home directory.")
    args = parser.parse_args(argv)

    config = load_config(args.home)
    logger = configure_logging(config.log_path)
    logger.info("Peach daemon booting with home=%s pid=%s", config.home, os.getpid())
    write_pid(config.pid_path)

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        logger.exception("APScheduler is required: %s", exc)
        remove_pid(config.pid_path, logger)
        return 1

    from .portfolio import PortfolioLedger
    from .memory import AgentMemory
    from .agent import PeachAgent
    from .discord_bot import PeachDiscord
    from .charts import ChartGenerator

    portfolio = PortfolioLedger(config.portfolio_db)
    memory = AgentMemory(config.memory_db)
    agent = PeachAgent(config, portfolio, memory, logger)
    discord_bot = PeachDiscord(config, agent, portfolio, memory, logger)
    chart_gen = ChartGenerator(logger)

    discord_bot.start()

    tz = ZoneInfo(config.timezone)
    scheduler = BlockingScheduler(timezone=tz)

    def shutdown(signum: int, _frame: object) -> None:
        logger.info("Received signal %s; shutting down.", signum)
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
        remove_pid(config.pid_path, logger)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Morning briefing + PDF
    scheduler.add_job(
        run_pipeline,
        trigger=CronTrigger(day_of_week="mon-fri", hour=config.schedule_hour,
                            minute=config.schedule_minute, timezone=tz),
        args=[config, logger, agent, discord_bot, portfolio, chart_gen],
        id="peach-market-briefing",
        replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=3600,
    )

    # Price + drawdown alert checker — every 5 min during market hours
    scheduler.add_job(
        check_alerts,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-16",
                            minute="*/5", timezone=tz),
        args=[config, logger, portfolio, discord_bot, memory],
        id="peach-alert-checker",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    # Daily 4 PM portfolio snapshot
    scheduler.add_job(
        record_portfolio_snapshot,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=tz),
        args=[config, logger, portfolio],
        id="peach-portfolio-snapshot",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    # Weekly Monday correlation heatmap
    scheduler.add_job(
        run_correlation_report,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=35, timezone=tz),
        args=[config, logger, portfolio, discord_bot],
        id="peach-correlation-report",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    if config.run_on_start:
        scheduler.add_job(
            run_pipeline,
            args=[config, logger, agent, discord_bot, portfolio, chart_gen],
            id="peach-run-on-start", replace_existing=True,
        )

    try:
        logger.info(
            "Peach scheduled at %02d:%02d %s Monday–Friday. "
            "Alert checker active 9–4. Correlation report Mondays 9:35.",
            config.schedule_hour, config.schedule_minute, config.timezone,
        )
        scheduler.start()
    except Exception as exc:
        logger.exception("Peach daemon crashed: %s", exc)
        remove_pid(config.pid_path, logger)
        return 1

    remove_pid(config.pid_path, logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
