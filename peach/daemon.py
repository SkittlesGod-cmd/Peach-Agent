"""Background scheduler daemon for Peach."""

from __future__ import annotations

import argparse
import logging
import os
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
    bot: object,
) -> None:
    logger.info("Starting Peach pipeline for tickers: %s", ", ".join(config.tickers))
    try:
        from .data_fetcher import MarketDataFetcher
        from .notifier import EmailNotifier

        market_data = MarketDataFetcher(config, logger).fetch()
        logger.info(
            "Fetched %d metrics and %d headlines",
            len(market_data.metrics),
            len(market_data.headlines),
        )

        from .agent import PeachAgent
        briefing: str
        if isinstance(agent, PeachAgent):
            briefing = agent.run_briefing(market_data)
        else:
            from .analyzer import MarketAnalyzer
            briefing = MarketAnalyzer(config, logger).analyze(market_data)

        EmailNotifier(config, logger).send(briefing)
        logger.info("Peach pipeline completed successfully.")

        # Send first 1 000 chars to Telegram as a nudge
        from .telegram_bot import PeachBot
        if isinstance(bot, PeachBot):
            snippet = briefing[:1000] + ("…" if len(briefing) > 1000 else "")
            bot.notify(f"Morning briefing ready:\n\n{snippet}")

    except Exception as exc:
        logger.exception("Peach pipeline failed: %s", exc)


def check_alerts(
    config: PeachConfig,
    logger: logging.Logger,
    portfolio: object,
    bot: object,
) -> None:
    try:
        import yfinance as yf
        from .portfolio import PortfolioLedger
        from .telegram_bot import PeachBot

        if not isinstance(portfolio, PortfolioLedger):
            return

        alerts = portfolio.get_active_alerts()
        if not alerts:
            return

        for alert in alerts:
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
                    if isinstance(bot, PeachBot):
                        bot.notify(msg)
            except Exception as exc:
                logger.warning("Alert check failed for %s: %s", alert.ticker, exc)
    except Exception as exc:
        logger.exception("Alert checker crashed: %s", exc)


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

    # Build shared objects — agent and bot persist for the lifetime of the daemon
    from .portfolio import PortfolioLedger
    from .memory import AgentMemory
    from .agent import PeachAgent
    from .telegram_bot import PeachBot

    portfolio = PortfolioLedger(config.portfolio_db)
    memory = AgentMemory(config.memory_db)
    agent = PeachAgent(config, portfolio, memory, logger)
    bot = PeachBot(config, agent, portfolio, memory, logger)

    bot.start()

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

    # Morning briefing
    scheduler.add_job(
        run_pipeline,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=config.schedule_hour,
            minute=config.schedule_minute,
            timezone=tz,
        ),
        args=[config, logger, agent, bot],
        id="peach-market-briefing",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Price-alert checker — runs every 5 minutes during regular market hours
    scheduler.add_job(
        check_alerts,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-16",
            minute="*/5",
            timezone=tz,
        ),
        args=[config, logger, portfolio, bot],
        id="peach-alert-checker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    if config.run_on_start:
        scheduler.add_job(
            run_pipeline,
            args=[config, logger, agent, bot],
            id="peach-run-on-start",
            replace_existing=True,
        )

    try:
        logger.info(
            "Peach scheduled at %02d:%02d %s Monday–Friday. Alert checker active 9–4 ET.",
            config.schedule_hour,
            config.schedule_minute,
            config.timezone,
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
