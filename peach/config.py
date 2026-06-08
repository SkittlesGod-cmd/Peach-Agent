"""Configuration loading for Peach.

Peach reads configuration from environment variables first, then from a JSON
file in the Peach home directory. The default home is the current directory so
the CLI works naturally from the project root, and it can be pinned with
PEACH_HOME or --home.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_TICKERS = ["SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT", "NVDA", "TSLA"]


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_home(home: str | None = None) -> Path:
    """Return the configured Peach runtime directory."""

    raw_home = home or os.getenv("PEACH_HOME") or os.getcwd()
    return Path(raw_home).expanduser().resolve()


@dataclass(frozen=True)
class PeachConfig:
    home: Path
    config_path: Path
    pid_path: Path
    log_path: Path
    tickers: list[str] = field(default_factory=lambda: DEFAULT_TICKERS.copy())
    timezone: str = "America/New_York"
    schedule_hour: int = 9
    schedule_minute: int = 0
    run_on_start: bool = False
    headline_limit: int = 10
    llm_provider: str = "peach"
    proxy_url: str = "https://peach-agent.vercel.app/api/analyze"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openrouter_api_key: str | None = None
    openrouter_model: str = "anthropic/claude-3-haiku"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1"
    alpha_vantage_api_key: str | None = None
    news_api_key: str | None = None
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None
    email_subject_prefix: str = "Peach Market Briefing"

    @property
    def has_email_settings(self) -> bool:
        return bool(
            self.smtp_host
            and self.smtp_port
            and self.smtp_username
            and self.smtp_password
            and self.email_from
            and self.email_to
        )


def load_config(home: str | None = None) -> PeachConfig:
    """Load Peach configuration from PEACH_HOME/peach_config.json and env vars."""

    resolved_home = resolve_home(home)
    config_path = resolved_home / "peach_config.json"
    data: dict[str, Any] = {}

    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError(f"{config_path} must contain a JSON object.")
            data = loaded

    tickers = _split_csv(os.getenv("PEACH_TICKERS"))
    if not tickers:
        configured_tickers = data.get("tickers", DEFAULT_TICKERS)
        tickers = [str(item).strip().upper() for item in configured_tickers if str(item).strip()]

    return PeachConfig(
        home=resolved_home,
        config_path=config_path,
        pid_path=resolved_home / ".peach.pid",
        log_path=resolved_home / "peach.log",
        tickers=tickers,
        timezone=os.getenv("PEACH_TIMEZONE", str(data.get("timezone", "America/New_York"))),
        schedule_hour=_as_int(os.getenv("PEACH_SCHEDULE_HOUR", data.get("schedule_hour")), 9),
        schedule_minute=_as_int(os.getenv("PEACH_SCHEDULE_MINUTE", data.get("schedule_minute")), 0),
        run_on_start=_as_bool(os.getenv("PEACH_RUN_ON_START", data.get("run_on_start")), False),
        headline_limit=_as_int(os.getenv("PEACH_HEADLINE_LIMIT", data.get("headline_limit")), 10),
        llm_provider=os.getenv("PEACH_LLM_PROVIDER", str(data.get("llm_provider", "peach"))).lower(),
        proxy_url=os.getenv("PEACH_PROXY_URL", str(data.get("proxy_url", "https://peach-agent.vercel.app/api/analyze"))),
        openai_api_key=os.getenv("OPENAI_API_KEY", data.get("openai_api_key")),
        openai_model=os.getenv("PEACH_OPENAI_MODEL", str(data.get("openai_model", "gpt-4o-mini"))),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", data.get("openrouter_api_key")),
        openrouter_model=os.getenv("PEACH_OPENROUTER_MODEL", str(data.get("openrouter_model", "anthropic/claude-3-haiku"))),
        ollama_url=os.getenv("OLLAMA_URL", str(data.get("ollama_url", "http://127.0.0.1:11434"))).rstrip("/"),
        ollama_model=os.getenv("PEACH_OLLAMA_MODEL", str(data.get("ollama_model", "llama3.1"))),
        alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY", data.get("alpha_vantage_api_key")),
        news_api_key=os.getenv("NEWS_API_KEY", data.get("news_api_key")),
        smtp_host=os.getenv("SMTP_HOST", str(data.get("smtp_host", "smtp.gmail.com"))),
        smtp_port=_as_int(os.getenv("SMTP_PORT", data.get("smtp_port")), 587),
        smtp_username=os.getenv("SMTP_USERNAME", data.get("smtp_username")),
        smtp_password=os.getenv("SMTP_PASSWORD", data.get("smtp_password")),
        email_from=os.getenv("PEACH_EMAIL_FROM", data.get("email_from")),
        email_to=os.getenv("PEACH_EMAIL_TO", data.get("email_to")),
        email_subject_prefix=os.getenv(
            "PEACH_EMAIL_SUBJECT_PREFIX",
            str(data.get("email_subject_prefix", "Peach Market Briefing")),
        ),
    )
