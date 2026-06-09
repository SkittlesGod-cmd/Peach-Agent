"""Chart generation for Peach — candlesticks, P&L bars, sector pie, correlation heatmap."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import yfinance as yf

if TYPE_CHECKING:
    from .portfolio import Position

_PEACH   = "#e0784c"
_GREEN   = "#4ade80"
_RED     = "#f87171"
_BG      = "#18181b"
_SURFACE = "#27272a"
_MUTED   = "#71717a"
_TEXT    = "#e4e4e7"

_PALETTE = [_PEACH, _GREEN, "#60a5fa", "#f59e0b", "#a78bfa",
            "#34d399", "#f87171", "#38bdf8", "#fb923c", "#c084fc"]

# mplfinance style
_MC = mpf.make_marketcolors(
    up=_GREEN, down=_RED,
    wick={"up": _GREEN, "down": _RED},
    volume={"up": _GREEN, "down": _RED},
    edge="none",
)
_MPF_STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    marketcolors=_MC,
    facecolor=_BG,
    figcolor=_BG,
    gridcolor=_SURFACE,
    gridstyle="--",
    gridaxis="both",
    y_on_right=False,
    rc={
        "axes.labelcolor": _MUTED,
        "axes.edgecolor": _SURFACE,
        "xtick.color": _MUTED,
        "ytick.color": _MUTED,
        "font.family": "sans-serif",
    },
)

_CORR_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "peach_corr", [_RED, _BG, _GREEN]
)


def _dark_fig(*args, **kwargs):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(*args, **kwargs)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    for spine in ax.spines.values():
        spine.set_edgecolor(_SURFACE)
    ax.tick_params(colors=_MUTED, labelsize=9)
    return fig, ax


def _to_png(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


class ChartGenerator:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("peach.charts")

    # ── Price / OHLCV ──────────────────────────────────────────────────────────

    def price_chart(self, ticker: str, period: str = "1mo") -> bytes:
        data = yf.download(ticker, period=period, interval="1d",
                           auto_adjust=True, progress=False)
        if data.empty:
            raise ValueError(f"No price data for {ticker}")

        # Flatten multi-level columns that newer yfinance returns
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

        fig, axes = mpf.plot(
            data,
            type="candle",
            style=_MPF_STYLE,
            title=f"\n{ticker}  ·  {period}",
            volume=True,
            returnfig=True,
            figsize=(12, 7),
        )
        fig.patch.set_facecolor(_BG)
        axes[0].title.set_color(_TEXT)
        axes[0].title.set_fontsize(13)
        return _to_png(fig)

    # ── Portfolio P&L bar ──────────────────────────────────────────────────────

    def portfolio_pnl_chart(self, positions: list[Position]) -> bytes:
        if not positions:
            raise ValueError("No positions")

        rows = []
        for pos in positions:
            try:
                info = yf.Ticker(pos.ticker).info
                current = info.get("currentPrice") or info.get("regularMarketPrice")
                if current:
                    pnl = (float(current) - pos.cost_basis) * pos.shares
                    rows.append((pos.ticker, pnl))
            except Exception:
                pass

        if not rows:
            raise ValueError("Could not fetch current prices for P&L chart")

        rows.sort(key=lambda x: x[1])
        tickers, pnls = zip(*rows)
        colors = [_GREEN if p >= 0 else _RED for p in pnls]

        fig, ax = _dark_fig(figsize=(10, max(4, len(tickers) * 0.55)))
        bars = ax.barh(tickers, pnls, color=colors, height=0.6)
        ax.axvline(0, color=_MUTED, linewidth=0.8, linestyle="--")

        # Label each bar
        for bar, pnl in zip(bars, pnls):
            xpos = bar.get_width() + (max(abs(p) for p in pnls) * 0.01)
            ax.text(xpos if pnl >= 0 else -xpos, bar.get_y() + bar.get_height() / 2,
                    f"${pnl:+,.0f}", va="center", ha="left" if pnl >= 0 else "right",
                    color=_GREEN if pnl >= 0 else _RED, fontsize=8)

        ax.set_xlabel("Unrealized P&L  ($)", color=_MUTED, fontsize=9)
        ax.set_title("Portfolio · Unrealized P&L", color=_TEXT, fontsize=13, pad=12)
        ax.tick_params(axis="y", labelcolor=_TEXT, labelsize=10)
        fig.tight_layout()
        return _to_png(fig)

    # ── Sector allocation pie ──────────────────────────────────────────────────

    def sector_allocation_chart(self, positions: list[Position]) -> bytes:
        if not positions:
            raise ValueError("No positions")

        sector_values: dict[str, float] = {}
        for pos in positions:
            try:
                info = yf.Ticker(pos.ticker).info
                current = info.get("currentPrice") or info.get("regularMarketPrice") or pos.cost_basis
                sector = info.get("sector") or "Unknown"
                sector_values[sector] = sector_values.get(sector, 0) + float(current) * pos.shares
            except Exception:
                sector_values.setdefault("Unknown", 0)

        if not sector_values:
            raise ValueError("No sector data")

        labels = list(sector_values.keys())
        sizes = list(sector_values.values())
        colors = _PALETTE[: len(labels)]

        fig, ax = plt.subplots(figsize=(8, 8))
        fig.patch.set_facecolor(_BG)
        ax.set_facecolor(_BG)

        wedges, _, autotexts = ax.pie(
            sizes, labels=labels, colors=colors,
            autopct="%1.1f%%", pctdistance=0.82,
            wedgeprops={"linewidth": 2, "edgecolor": _BG},
            textprops={"color": _TEXT, "fontsize": 10},
        )
        for at in autotexts:
            at.set_fontsize(9)
            at.set_color(_BG)

        ax.set_title("Portfolio · Sector Allocation", color=_TEXT, fontsize=13, pad=16)
        fig.tight_layout()
        return _to_png(fig)

    # ── Portfolio value over time ──────────────────────────────────────────────

    def portfolio_history_chart(self, snapshots: list[dict]) -> bytes:
        if len(snapshots) < 2:
            raise ValueError("Need at least 2 snapshots for history chart")

        dates = pd.to_datetime([s["snapshot_date"] for s in snapshots])
        values = [s["total_value"] for s in snapshots]
        costs  = [s["total_cost"]  for s in snapshots]

        fig, ax = _dark_fig(figsize=(12, 5))
        ax.plot(dates, values, color=_PEACH, linewidth=2, label="Market Value", zorder=3)
        ax.plot(dates, costs,  color=_MUTED, linewidth=1.2, linestyle="--", label="Cost Basis")

        # Shade profit/loss zone
        vals_arr = pd.Series(values, index=dates)
        cost_arr = pd.Series(costs,  index=dates)
        ax.fill_between(dates, values, costs,
                        where=[v >= c for v, c in zip(values, costs)],
                        alpha=0.15, color=_GREEN, label="_nolegend_")
        ax.fill_between(dates, values, costs,
                        where=[v < c for v, c in zip(values, costs)],
                        alpha=0.15, color=_RED, label="_nolegend_")

        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=2))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

        legend = ax.legend(facecolor=_SURFACE, edgecolor="none", labelcolor=_TEXT, fontsize=9)
        ax.set_title("Portfolio Value  ·  Historical", color=_TEXT, fontsize=13, pad=12)
        fig.tight_layout()
        return _to_png(fig)

    # ── Multi-ticker comparison ────────────────────────────────────────────────

    def comparison_chart(self, tickers: list[str], period: str = "3mo") -> bytes:
        if not tickers:
            raise ValueError("No tickers")

        raw = yf.download(tickers if len(tickers) > 1 else tickers[0],
                          period=period, interval="1d", auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError("No data")

        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]] if "Close" in raw.columns else raw

        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])

        close = close.dropna(how="all")
        # Normalize: cumulative return from start
        norm = (close / close.iloc[0] - 1) * 100

        fig, ax = _dark_fig(figsize=(12, 6))
        for i, col in enumerate(norm.columns):
            color = _PALETTE[i % len(_PALETTE)]
            ax.plot(norm.index, norm[col], color=color, linewidth=2, label=col)

        ax.axhline(0, color=_MUTED, linewidth=0.8, linestyle="--")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:+.1f}%"))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=2))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

        legend = ax.legend(facecolor=_SURFACE, edgecolor="none", labelcolor=_TEXT, fontsize=9)
        tickers_str = "  ·  ".join(norm.columns.tolist())
        ax.set_title(f"Return Comparison  ·  {period}\n{tickers_str}",
                     color=_TEXT, fontsize=11, pad=12)
        fig.tight_layout()
        return _to_png(fig)

    # ── Correlation heatmap ────────────────────────────────────────────────────

    def correlation_heatmap(self, tickers: list[str], period: str = "3mo") -> bytes:
        if len(tickers) < 2:
            raise ValueError("Need at least 2 tickers for correlation")

        raw = yf.download(tickers, period=period, interval="1d",
                          auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError("No data for correlation")

        close = raw["Close"] if "Close" in raw.columns else raw
        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])

        close = close.dropna(how="all")
        returns = close.pct_change().dropna(how="all")
        corr = returns.corr().round(2)

        n = len(corr)
        fig, ax = plt.subplots(figsize=(max(6, n), max(5, n * 0.8)))
        fig.patch.set_facecolor(_BG)
        ax.set_facecolor(_BG)

        im = ax.imshow(corr.values, cmap=_CORR_CMAP, vmin=-1, vmax=1, aspect="auto")

        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(corr.columns, rotation=45, ha="right", color=_MUTED, fontsize=9)
        ax.set_yticklabels(corr.index, color=_MUTED, fontsize=9)

        for i in range(n):
            for j in range(n):
                val = corr.values[i, j]
                ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                        color="white" if abs(val) < 0.6 else _BG, fontsize=8, fontweight="bold")

        cb = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.yaxis.set_tick_params(color=_MUTED, labelsize=8)
        plt.setp(cb.ax.yaxis.get_ticklabels(), color=_MUTED)

        ax.set_title(f"30-Day Return Correlation  ·  {period}", color=_TEXT, fontsize=13, pad=12)
        fig.tight_layout()
        return _to_png(fig)
