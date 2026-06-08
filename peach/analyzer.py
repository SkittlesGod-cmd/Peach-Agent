"""LLM-backed analysis core for Peach."""

from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import Any

import requests

from .config import PeachConfig
from .data_fetcher import AggregatedMarketData, StockMetric


SYSTEM_INSTRUCTIONS = """You are Peach, a precise pre-market equity briefing agent.

Write a concise Markdown market briefing for an active trader. Use only the
provided data. Make uncertainty explicit. Do not invent prices, catalysts, or
headlines. Include:

1. Macro Tape
2. Unusual Price/Volume Standouts
3. Market Sentiment
4. Lookout List with 2-3 tickers and technical justification
5. Risk Notes

The Lookout List must cite specific observed metrics or headline catalysts from
the payload. Keep the report readable and action-oriented, not promotional.
"""


class MarketAnalyzer:
    def __init__(self, config: PeachConfig, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("peach")
        self.session = requests.Session()

    def analyze(self, market_data: AggregatedMarketData) -> str:
        prompt = self._build_prompt(market_data)

        try:
            if self.config.llm_provider == "peach":
                return self._analyze_with_peach_proxy(prompt)
            if self.config.llm_provider == "openrouter":
                return self._analyze_with_openrouter(prompt)
            if self.config.llm_provider == "openai":
                return self._analyze_with_openai(prompt)
            if self.config.llm_provider == "ollama":
                return self._analyze_with_ollama(prompt)
            raise ValueError(f"Unsupported LLM provider: {self.config.llm_provider}")
        except Exception as exc:
            self.logger.exception("LLM analysis failed; using deterministic fallback: %s", exc)
            return self._fallback_analysis(market_data, str(exc))

    def _build_prompt(self, market_data: AggregatedMarketData) -> str:
        payload = market_data.to_prompt_payload()
        return (
            "Raw market payload follows as JSON:\n"
            f"{json.dumps(payload, indent=2, sort_keys=True)}"
        )

    def _analyze_with_peach_proxy(self, prompt: str) -> str:
        response = self.session.post(
            self.config.proxy_url,
            json={
                "model": self.config.openrouter_model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        content = (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )
        if not content:
            raise RuntimeError("Peach proxy returned an empty analysis.")
        return str(content).strip()

    def _analyze_with_openrouter(self, prompt: str) -> str:
        if not self.config.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required when PEACH_LLM_PROVIDER=openrouter.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the openai package to use OpenRouter analysis.") from exc

        client = OpenAI(
            api_key=self.config.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        response = client.chat.completions.create(
            model=self.config.openrouter_model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenRouter returned an empty analysis.")
        return content.strip()

    def _analyze_with_openai(self, prompt: str) -> str:
        if not self.config.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when PEACH_LLM_PROVIDER=openai.")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the openai package to use OpenAI analysis.") from exc

        client = OpenAI(api_key=self.config.openai_api_key)
        response = client.chat.completions.create(
            model=self.config.openai_model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned an empty analysis.")
        return content.strip()

    def _analyze_with_ollama(self, prompt: str) -> str:
        full_prompt = f"{SYSTEM_INSTRUCTIONS}\n\n{prompt}"
        response = self.session.post(
            f"{self.config.ollama_url}/api/generate",
            json={
                "model": self.config.ollama_model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload.get("response")
        if not content:
            raise RuntimeError("Ollama returned an empty analysis.")
        return str(content).strip()

    def _fallback_analysis(self, market_data: AggregatedMarketData, failure_reason: str) -> str:
        sorted_metrics = sorted(
            [metric for metric in market_data.metrics if metric.percent_change is not None],
            key=lambda metric: abs(metric.percent_change or 0),
            reverse=True,
        )
        lookout = self._select_lookout(sorted_metrics)
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "# Peach Market Briefing",
            "",
            f"_Generated at {generated_at}. LLM analysis was unavailable; Peach used a deterministic fallback._",
            "",
            "## Macro Tape",
            "Peach fetched the configured index and equity basket. Treat this as a data-first snapshot, because the LLM provider was not reachable.",
            "",
            "## Unusual Price/Volume Standouts",
        ]

        if sorted_metrics:
            for metric in sorted_metrics[:5]:
                lines.append(
                    f"- **{metric.ticker}** closed at {self._money(metric.close)} "
                    f"({self._pct(metric.percent_change)}), volume {self._volume(metric.volume)} "
                    f"on {metric.trade_date or 'the latest available session'}."
                )
        else:
            lines.append("- No usable price-change metrics were available.")

        lines.extend(["", "## Market Sentiment"])
        if market_data.headlines:
            for headline in market_data.headlines[:5]:
                source = f" ({headline.source})" if headline.source else ""
                lines.append(f"- {headline.title}{source}")
        else:
            lines.append("- No external headlines were available.")

        lines.extend(["", "## Lookout List"])
        if lookout:
            for metric in lookout:
                lines.append(
                    f"- **{metric.ticker}**: Watch for continuation or reversal after a "
                    f"{self._pct(metric.percent_change)} prior-session move. Latest close: "
                    f"{self._money(metric.close)}; volume: {self._volume(metric.volume)}."
                )
        else:
            lines.append("- No specific lookout candidates could be selected from the available data.")

        lines.extend(
            [
                "",
                "## Risk Notes",
                f"- LLM provider failure: `{failure_reason}`",
                "- Verify live pre-market quotes and liquidity before taking action.",
                "- This briefing is informational and is not financial advice.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _select_lookout(metrics: list[StockMetric]) -> list[StockMetric]:
        return metrics[:3]

    @staticmethod
    def _money(value: float | None) -> str:
        return "n/a" if value is None else f"${value:,.2f}"

    @staticmethod
    def _pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:+.2f}%"

    @staticmethod
    def _volume(value: int | None) -> str:
        return "n/a" if value is None else f"{value:,}"
