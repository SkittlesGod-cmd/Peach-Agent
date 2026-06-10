"""Terminal CLI controller for Peach."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import __version__
from .config import load_config
from .logging_setup import configure_logging


# ── Process helpers ────────────────────────────────────────────────────────────

def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(pid_path: Path) -> int | None:
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _next_run_time(config) -> str:
    try:
        tz = ZoneInfo(config.timezone)
        now = datetime.now(tz)
        h, m = config.schedule_hour, config.schedule_minute
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        days = 0
        while True:
            check = candidate + timedelta(days=days)
            if check > now and check.weekday() < 5:
                return check.strftime("%a %b %d  %H:%M %Z")
            days += 1
            if days > 14:
                break
    except Exception:
        pass
    return "unknown"


# ── Commands ───────────────────────────────────────────────────────────────────

def command_start(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    config.home.mkdir(parents=True, exist_ok=True)
    logger = configure_logging(config.log_path, include_console=args.verbose)

    # Warn if config is world-readable
    if config.config_path.exists():
        mode = config.config_path.stat().st_mode & 0o177
        if mode & 0o044:
            print(
                f"  Warning: {config.config_path} may be readable by others "
                f"(mode {oct(mode & 0o777)}). Run: chmod 600 {config.config_path}"
            )

    existing_pid = read_pid(config.pid_path)
    if existing_pid and is_process_running(existing_pid):
        print(f"Peach is already running (PID {existing_pid}).")
        return 0
    if existing_pid and config.pid_path.exists():
        config.pid_path.unlink()

    env = os.environ.copy()
    env["PEACH_HOME"] = str(config.home)

    with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as stdout, open(os.devnull, "wb") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", "peach.daemon", "--home", str(config.home)],
            cwd=str(config.home),
            stdin=stdin, stdout=stdout, stderr=stderr,
            env=env, start_new_session=True, close_fds=True,
        )

    config.pid_path.write_text(str(process.pid), encoding="utf-8")
    time.sleep(0.5)

    if process.poll() is not None or not is_process_running(process.pid):
        logger.error("Daemon failed to stay alive; exit_code=%s", process.poll())
        if config.pid_path.exists():
            config.pid_path.unlink()
        print(f"Peach failed to start. Check {config.log_path}.")
        return 1

    print(f"Peach started (PID {process.pid}).")
    print(f"  Next run:  {_next_run_time(config)}")
    print(f"  Logs:      {config.log_path}")
    return 0


def command_stop(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    pid = read_pid(config.pid_path)
    if not pid:
        print("Peach is already stopped.")
        return 0
    if not is_process_running(pid):
        if config.pid_path.exists():
            config.pid_path.unlink()
        print("Peach was not running; removed stale PID file.")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except PermissionError:
        print(f"Cannot stop PID {pid}: permission denied.")
        return 1
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if not is_process_running(pid):
            if config.pid_path.exists():
                config.pid_path.unlink()
            print(f"Peach stopped (PID {pid}).")
            return 0
        time.sleep(0.25)
    print(f"Peach did not stop within {args.timeout}s.")
    return 1


def command_status(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    pid = read_pid(config.pid_path)

    running = pid and is_process_running(pid)
    status_line = f"running  (PID {pid})" if running else "stopped"
    print(f"  Peach:      {status_line}")
    print(f"  Home:       {config.home}")
    print(f"  Next run:   {_next_run_time(config)}")
    print(f"  Tickers:    {', '.join(config.tickers[:6])}{'…' if len(config.tickers) > 6 else ''}")

    # Briefing freshness
    briefing = config.home / "briefing.md"
    if briefing.exists():
        mtime = datetime.fromtimestamp(briefing.stat().st_mtime)
        print(f"  Last brief: {mtime.strftime('%a %b %d %H:%M')}")

    # Portfolio + alerts
    try:
        from .portfolio import PortfolioLedger
        ledger = PortfolioLedger(config.portfolio_db)
        positions = ledger.get_all_positions()
        alerts = ledger.get_active_alerts()
        print(f"  Positions:  {len(positions)}")
        print(f"  Alerts:     {len(alerts)} active")
    except Exception:
        pass

    # Log size
    if config.log_path.exists():
        kb = config.log_path.stat().st_size / 1024
        print(f"  Log:        {kb:.0f} KB  ({config.log_path})")

    return 0 if running else 1


def command_run(args: argparse.Namespace) -> int:
    """Run a briefing right now — prints to stdout and saves to briefing.md."""
    config = load_config(args.home)
    config.home.mkdir(parents=True, exist_ok=True)
    logger = configure_logging(config.log_path, include_console=True)

    from .portfolio import PortfolioLedger
    from .memory import AgentMemory
    from .agent import PeachAgent
    from .data_fetcher import MarketDataFetcher
    from .notifier import EmailNotifier

    portfolio = PortfolioLedger(config.portfolio_db)
    memory = AgentMemory(config.memory_db)
    agent = PeachAgent(config, portfolio, memory, logger)

    print("Fetching market data…")
    market_data = MarketDataFetcher(config, logger).fetch()
    print(f"  {len(market_data.metrics)} metrics  ·  {len(market_data.headlines)} headlines  ·  macro={list(market_data.macro.keys())}")

    print("Running agent loop…")
    briefing = agent.run_briefing(market_data)

    if not args.no_email:
        EmailNotifier(config, logger).send(briefing)

    print("\n" + "─" * 72)
    print(briefing)
    print("─" * 72)
    print(f"\nSaved to {config.home / 'briefing.md'}")
    return 0


def command_logs(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    if not config.log_path.exists():
        print(f"No log file at {config.log_path}")
        return 1
    try:
        cmd = ["tail", f"-{args.lines}", str(config.log_path)]
        if args.follow:
            cmd = ["tail", "-f", f"-{args.lines}", str(config.log_path)]
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass
    return 0


def command_upgrade(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    install_dir = Path(__file__).parent.parent

    pid = read_pid(config.pid_path)
    was_running = bool(pid and is_process_running(pid))
    if was_running:
        print("Stopping Peach…")
        command_stop(args)

    # git pull
    git_dir = install_dir / ".git"
    if not git_dir.exists():
        print(f"No git repo at {install_dir}. Cannot upgrade automatically.")
        return 1

    print(f"Pulling latest ({install_dir})…")
    result = subprocess.run(
        ["git", "-C", str(install_dir), "pull", "--ff-only"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"git pull failed:\n{result.stderr.strip()}")
        return 1
    print(result.stdout.strip() or "Already up to date.")

    # pip install
    pip = Path(sys.executable).parent / "pip"
    print("Updating dependencies…")
    req_file = install_dir / "requirements-peach.txt"
    result = subprocess.run(
        [str(pip), "install", "-q", "-r", str(req_file), str(install_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"pip install failed:\n{result.stderr.strip()}")
        return 1
    print("Dependencies updated.")

    if was_running:
        print("Restarting Peach…")
        command_start(args)

    print("Upgrade complete.")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    ok = True

    def _ok(msg: str) -> None:
        print(f"  ✓  {msg}")

    def _warn(msg: str) -> None:
        print(f"  ⚠  {msg}")

    def _fail(msg: str) -> None:
        nonlocal ok
        ok = False
        print(f"  ✗  {msg}")

    print()

    # Python version
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 9):
        _ok(f"Python {major}.{minor}")
    else:
        _fail(f"Python {major}.{minor}  (need 3.9+)")

    # Config file
    if config.config_path.exists():
        mode = config.config_path.stat().st_mode & 0o777
        if mode & 0o044:
            _warn(f"Config file is readable by others (mode {oct(mode)}) — run: chmod 600 {config.config_path}")
        else:
            _ok(f"Config file is private  ({config.config_path})")
    else:
        _warn(f"Config not found at {config.config_path}  (defaults used)")

    # LLM proxy
    try:
        import requests
        r = requests.get(config.proxy_url.rsplit("/", 1)[0], timeout=5)
        _ok("LLM proxy reachable")
    except Exception as exc:
        _fail(f"LLM proxy unreachable: {exc}")

    # yfinance data
    try:
        import yfinance as yf
        info = yf.Ticker("SPY").info
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        _ok(f"yfinance data  (SPY ${price})" if price else "yfinance responded (no price)")
    except Exception as exc:
        _fail(f"yfinance failed: {exc}")

    # Discord
    if config.discord_token:
        try:
            import requests
            r = requests.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {config.discord_token}"},
                timeout=5,
            )
            if r.ok:
                _ok(f"Discord bot: {r.json().get('username')}")
            else:
                _fail(f"Discord token invalid ({r.status_code})")
        except Exception as exc:
            _fail(f"Discord check failed: {exc}")
    else:
        print("  –  Discord not configured")

    # Email
    if config.has_email_settings:
        _ok(f"Email → {config.email_to}")
    else:
        print(f"  –  Email not configured  (briefings → {config.home / 'briefing.md'})")

    # Dependencies
    critical = ["apscheduler", "yfinance", "requests", "fpdf", "mplfinance", "discord"]
    missing = []
    for dep in critical:
        try:
            __import__(dep.replace("-", "_"))
        except ImportError:
            missing.append(dep)
    if missing:
        _fail(f"Missing packages: {', '.join(missing)}  — run: pip install -r requirements-peach.txt")
    else:
        _ok("Core packages installed")

    # Disk space
    import shutil
    free_gb = shutil.disk_usage(config.home).free / 1024 ** 3
    if free_gb < 0.5:
        _warn(f"Low disk space: {free_gb:.1f} GB free")
    else:
        _ok(f"Disk: {free_gb:.1f} GB free")

    # Log file
    if config.log_path.exists():
        kb = config.log_path.stat().st_size / 1024
        _ok(f"Log: {kb:.0f} KB  ({config.log_path})")

    print()
    print("  Peach looks healthy." if ok else "  Issues found — see ✗ items above.")
    print()
    return 0 if ok else 1


# ── Parser ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="peach",
        description="Peach — pre-market intelligence agent.",
    )
    parser.add_argument("--home", help="Peach home directory (or set PEACH_HOME).")
    parser.add_argument("--verbose", action="store_true", help="Print logs to terminal.")
    parser.add_argument("--version", action="version", version=f"peach {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("start",  help="Start the background daemon.").set_defaults(func=command_start)
    sub.add_parser("status", help="Show daemon status, next run, and portfolio summary.").set_defaults(func=command_status)

    stop_p = sub.add_parser("stop", help="Stop the daemon.")
    stop_p.add_argument("--timeout", type=float, default=10.0)
    stop_p.set_defaults(func=command_stop)

    run_p = sub.add_parser("run", help="Run a briefing now and print to stdout.")
    run_p.add_argument("--no-email", action="store_true", help="Skip email delivery.")
    run_p.set_defaults(func=command_run)

    logs_p = sub.add_parser("logs", help="Tail the Peach log file.")
    logs_p.add_argument("-n", "--lines", type=int, default=50, help="Number of lines (default 50).")
    logs_p.add_argument("-f", "--follow", action="store_true", help="Follow (like tail -f).")
    logs_p.set_defaults(func=command_logs)

    sub.add_parser("upgrade", help="Pull latest code, update deps, restart if needed.").set_defaults(func=command_upgrade)
    sub.add_parser("doctor",  help="Check configuration and connectivity.").set_defaults(func=command_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
