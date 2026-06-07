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


def run_pipeline(config: PeachConfig, logger: logging.Logger) -> None:
    logger.info("Starting Peach pipeline for tickers: %s", ", ".join(config.tickers))
    try:
        from .analyzer import MarketAnalyzer
        from .data_fetcher import MarketDataFetcher
        from .notifier import EmailNotifier

        market_data = MarketDataFetcher(config, logger).fetch()
        logger.info(
            "Fetched %d metrics and %d headlines",
            len(market_data.metrics),
            len(market_data.headlines),
        )
        briefing = MarketAnalyzer(config, logger).analyze(market_data)
        EmailNotifier(config, logger).send(briefing)
        logger.info("Peach pipeline completed successfully")
    except Exception as exc:
        logger.exception("Peach pipeline failed without crashing daemon: %s", exc)


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
    parser.add_argument("--home", help="Peach home directory containing config, pid, and log files.")
    args = parser.parse_args(argv)

    config = load_config(args.home)
    logger = configure_logging(config.log_path)
    logger.info("Peach daemon booting with home=%s pid=%s", config.home, os.getpid())
    write_pid(config.pid_path)

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        logger.exception("APScheduler is required to run Peach: %s", exc)
        remove_pid(config.pid_path, logger)
        return 1

    scheduler = BlockingScheduler(timezone=ZoneInfo(config.timezone))

    def shutdown(signum: int, _frame: object) -> None:
        logger.info("Received signal %s; shutting down Peach daemon", signum)
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            logger.exception("Scheduler shutdown raised unexpectedly")
        remove_pid(config.pid_path, logger)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    scheduler.add_job(
        run_pipeline,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=config.schedule_hour,
            minute=config.schedule_minute,
            timezone=ZoneInfo(config.timezone),
        ),
        args=[config, logger],
        id="peach-market-briefing",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    if config.run_on_start:
        scheduler.add_job(
            run_pipeline,
            args=[config, logger],
            id="peach-run-on-start",
            replace_existing=True,
        )

    try:
        logger.info(
            "Peach scheduled for %02d:%02d %s Monday-Friday",
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
