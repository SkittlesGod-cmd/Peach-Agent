"""Terminal CLI controller for Peach."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .config import load_config
from .logging_setup import configure_logging


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
        raw_pid = pid_path.read_text(encoding="utf-8").strip()
        return int(raw_pid)
    except FileNotFoundError:
        return None
    except ValueError:
        return None


def command_start(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    config.home.mkdir(parents=True, exist_ok=True)
    logger = configure_logging(config.log_path, include_console=args.verbose)

    existing_pid = read_pid(config.pid_path)
    if existing_pid and is_process_running(existing_pid):
        print(f"Peach is already running with PID {existing_pid}.")
        return 0
    if existing_pid and config.pid_path.exists():
        config.pid_path.unlink()

    env = os.environ.copy()
    env["PEACH_HOME"] = str(config.home)

    with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as stdout, open(
        os.devnull, "wb"
    ) as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", "peach.daemon", "--home", str(config.home)],
            cwd=str(config.home),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=env,
            start_new_session=True,
            close_fds=True,
        )

    config.pid_path.write_text(str(process.pid), encoding="utf-8")
    time.sleep(0.5)

    exit_code = process.poll()
    if exit_code is not None or not is_process_running(process.pid):
        logger.error("Peach daemon failed to stay alive after start; exit_code=%s", exit_code)
        if config.pid_path.exists():
            config.pid_path.unlink()
        print(f"Peach failed to start. Check {config.log_path}.")
        return 1

    print(f"Peach started with PID {process.pid}.")
    print(f"PID file: {config.pid_path}")
    print(f"Log file: {config.log_path}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    pid = read_pid(config.pid_path)
    if not pid:
        print(f"Peach is stopped. No PID file found at {config.pid_path}.")
        return 1
    if is_process_running(pid):
        print(f"Peach is running with PID {pid}.")
        print(f"Log file: {config.log_path}")
        return 0
    print(f"Peach is stopped. Stale PID file found at {config.pid_path}.")
    return 1


def command_stop(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    pid = read_pid(config.pid_path)
    if not pid:
        print(f"Peach is already stopped. No PID file found at {config.pid_path}.")
        return 0

    if not is_process_running(pid):
        if config.pid_path.exists():
            config.pid_path.unlink()
        print("Peach was not running; removed stale PID file.")
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
    except PermissionError:
        print(f"Peach could not stop PID {pid}: permission denied by the OS.")
        return 1

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if not is_process_running(pid):
            if config.pid_path.exists():
                config.pid_path.unlink()
            print(f"Peach stopped PID {pid}.")
            return 0
        time.sleep(0.25)

    print(f"Peach did not stop within {args.timeout} seconds; leaving PID file in place.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="peach",
        description="Peach local AI pre-market briefing agent.",
    )
    parser.add_argument(
        "--home",
        help="Directory for peach_config.json, .peach.pid, and peach.log. Defaults to PEACH_HOME or the current directory.",
    )
    parser.add_argument("--verbose", action="store_true", help="Also print controller logs to the terminal.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start Peach as a detached background daemon.")
    start_parser.set_defaults(func=command_start)

    status_parser = subparsers.add_parser("status", help="Show whether Peach is running.")
    status_parser.set_defaults(func=command_status)

    stop_parser = subparsers.add_parser("stop", help="Stop Peach and clean up its PID file.")
    stop_parser.add_argument("--timeout", type=float, default=10.0, help="Seconds to wait for graceful shutdown.")
    stop_parser.set_defaults(func=command_stop)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
