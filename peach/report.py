"""PDF morning brief generator for Peach."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from typing import TYPE_CHECKING

from fpdf import FPDF

if TYPE_CHECKING:
    from .portfolio import Position


# ── Colours (RGB) ─────────────────────────────────────────────────────────────
_PEACH   = (224, 120, 76)
_DARK    = (28, 28, 30)
_MID     = (99, 99, 102)
_LIGHT   = (229, 229, 234)
_WHITE   = (255, 255, 255)
_GREEN   = (52, 199, 89)
_RED     = (255, 59, 48)


class _Brief(FPDF):
    """fpdf2 subclass with Peach branding."""

    def header(self) -> None:
        self.set_font("Helvetica", "B", 22)
        self.set_text_color(*_PEACH)
        self.cell(0, 10, "Peach", ln=True)

        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_MID)
        today = date.today().strftime("%A, %B %-d %Y")
        self.cell(0, 5, f"Morning Brief  ·  {today}", ln=True)

        self.set_draw_color(*_PEACH)
        self.set_line_width(0.5)
        self.line(10, self.get_y() + 2, 200, self.get_y() + 2)
        self.ln(8)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*_MID)
        self.cell(0, 6, f"Peach Agent  ·  Page {self.page_no()}", align="C")

    def section(self, title: str) -> None:
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*_PEACH)
        self.ln(3)
        self.cell(0, 8, title, ln=True)
        self.set_text_color(*_DARK)

    def kv(self, label: str, value: str, value_color: tuple | None = None) -> None:
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_MID)
        self.cell(52, 6, label)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*(value_color or _DARK))
        self.cell(0, 6, value, ln=True)
        self.set_text_color(*_DARK)

    def table_header(self, cols: list[tuple[str, int]]) -> None:
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(*_LIGHT)
        self.set_text_color(*_MID)
        for label, width in cols:
            self.cell(width, 6, label, border="B", fill=True)
        self.ln()
        self.set_text_color(*_DARK)

    def table_row(self, cells: list[tuple[str, int]], colors: list[tuple | None] | None = None) -> None:
        self.set_font("Helvetica", "", 8)
        colors = colors or [None] * len(cells)
        for (text, width), color in zip(cells, colors):
            self.set_text_color(*(color or _DARK))
            self.cell(width, 5, str(text))
        self.ln()
        self.set_text_color(*_DARK)


# ── Public API ─────────────────────────────────────────────────────────────────

class ReportGenerator:
    def morning_brief(
        self,
        briefing: str,
        macro: dict,
        positions: list[Position],
        chart_bytes: dict[str, bytes] | None = None,
    ) -> bytes:
        pdf = _Brief(orientation="P", unit="mm", format="A4")
        pdf.set_margins(12, 15, 12)
        pdf.set_auto_page_break(auto=True, margin=16)
        pdf.add_page()

        # ── Macro snapshot ────────────────────────────────────────────────────
        if macro:
            pdf.section("Macro Snapshot")
            _labels = {"VIX": "VIX (Fear Index)", "YIELD_10Y": "10Y Yield  (%)", "DXY": "Dollar  (DXY)"}
            for key, val in macro.items():
                price = val.get("price")
                chg = val.get("change_pct")
                label = _labels.get(key, key)
                if price is None:
                    continue
                chg_str = f"  ({chg:+.2f}%)" if chg is not None else ""
                color = _GREEN if (chg or 0) >= 0 else _RED
                pdf.kv(label, f"{price}{chg_str}", value_color=color)
            pdf.ln(2)

        # ── Portfolio ─────────────────────────────────────────────────────────
        if positions:
            pdf.section("Portfolio Positions")
            cols = [("Ticker", 24), ("Shares", 22), ("Cost Basis", 28), ("Entry Date", 28), ("Thesis", 70)]
            pdf.table_header(cols)
            for pos in positions:
                pdf.table_row([
                    (pos.ticker, 24),
                    (f"{pos.shares:,.2f}", 22),
                    (f"${pos.cost_basis:,.2f}", 28),
                    (pos.entry_date, 28),
                    ((pos.thesis or "")[:60], 70),
                ])
            pdf.ln(4)

        # ── Charts ────────────────────────────────────────────────────────────
        if chart_bytes:
            _tmpfiles: list[str] = []
            try:
                for title, img_data in chart_bytes.items():
                    if not img_data:
                        continue
                    pdf.section(title)
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp.write(img_data)
                        _tmpfiles.append(tmp.name)
                    pdf.image(_tmpfiles[-1], w=176)
                    pdf.ln(4)
            finally:
                for path in _tmpfiles:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

        # ── Briefing text ─────────────────────────────────────────────────────
        pdf.section("Analysis")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK)
        # Strip markdown-style bold/italic markers for clean PDF rendering
        clean = briefing.replace("**", "").replace("__", "").replace("##", "").replace("# ", "")
        pdf.multi_cell(0, 5, clean)

        return bytes(pdf.output())
