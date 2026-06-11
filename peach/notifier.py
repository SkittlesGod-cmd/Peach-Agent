"""Email notification engine for Peach."""

from __future__ import annotations

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import logging
import smtplib

import requests

from .config import PeachConfig


class EmailNotifier:
    def __init__(self, config: PeachConfig, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("peach")

    def send(self, markdown_report: str) -> None:
        # Always persist locally — email is a bonus delivery, not the only copy
        self._save_briefing(markdown_report)
        if not self.config.email_to:
            return

        subject = f"{self.config.email_subject_prefix} - {datetime.now().strftime('%Y-%m-%d')}"
        html_body = self._markdown_to_html(markdown_report)

        if self.config.has_email_settings:
            self._send_smtp(markdown_report, html_body, subject)
        else:
            self._send_via_proxy(html_body, subject)

    def _send_smtp(self, plain: str, html_body: str, subject: str) -> None:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self.config.email_from or ""
        message["To"] = self.config.email_to or ""
        message.attach(MIMEText(plain, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))
        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(self.config.smtp_username, self.config.smtp_password)
                smtp.send_message(message)
            self.logger.info("Sent Peach briefing email (SMTP) to %s", self.config.email_to)
        except smtplib.SMTPException as exc:
            self.logger.exception("SMTP transmission failed: %s", exc)
            raise
        except OSError as exc:
            self.logger.exception("Network error while sending email: %s", exc)
            raise

    def _send_via_proxy(self, html_body: str, subject: str) -> None:
        base = self.config.proxy_url.rsplit("/api/", 1)[0]
        url = f"{base}/api/send-email"
        try:
            resp = requests.post(
                url,
                json={"to": self.config.email_to, "subject": subject, "html": html_body},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self.logger.info("Sent Peach briefing email (proxy) to %s (id=%s)",
                             self.config.email_to, data.get("id", "?"))
        except Exception as exc:
            self.logger.exception("Proxy email delivery failed: %s", exc)
            raise

    def _save_briefing(self, markdown_report: str) -> None:
        path = self.config.home / "briefing.md"
        path.write_text(markdown_report, encoding="utf-8")
        self.logger.info("Briefing saved to %s", path)

    @staticmethod
    def _markdown_to_html(text: str) -> str:  # noqa: C901
        """Render the briefing: light peach theme, SVG chart, wave header, Gmail-safe inline styles."""
        import re

        # ── Inline markdown helpers ───────────────────────────────────────────
        def inline(s: str) -> str:
            s = html.escape(s)
            s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
            s = re.sub(r'\b_(.+?)_\b', r'<em>\1</em>', s)
            s = re.sub(r'`(.+?)`',
                       r'<code style="background:#fde8d8;padding:1px 5px;border-radius:3px;'
                       r'font-family:monospace;font-size:12px;color:#8a3010">\1</code>', s)
            return s

        def parse_table_lines(lines: list[str]) -> list[list[str]]:
            rows = []
            for ln in lines:
                s = ln.strip()
                if not s.startswith("|"):
                    continue
                cells = [c.strip() for c in s.strip("|").split("|")]
                if all(re.match(r"^[-: ]+$", c) for c in cells if c):
                    continue
                rows.append(cells)
            return rows

        def render_table(rows: list[list[str]]) -> str:
            if not rows:
                return ""
            out = ('<table style="width:100%;border-collapse:collapse;font-size:13px;'
                   'margin:10px 0;border-radius:6px;overflow:hidden;">')
            for i, row in enumerate(rows):
                bg = "#fdebd8" if i == 0 else ("#ffffff" if i % 2 == 0 else "#fff7f2")
                fw = "600" if i == 0 else "400"
                out += f'<tr style="background:{bg};">'
                for cell in row:
                    out += (f'<td style="padding:8px 12px;border-bottom:1px solid #fae0cc;'
                            f'font-weight:{fw};color:#2a1a10;white-space:nowrap;">'
                            f'{inline(cell)}</td>')
                out += "</tr>"
            out += "</table>"
            return out

        def render_bullets(items: list[str]) -> str:
            out = ""
            for item in items:
                out += (
                    '<div style="display:flex;align-items:flex-start;margin-bottom:8px;">'
                    '<div style="width:3px;min-width:3px;background:#e07840;border-radius:2px;'
                    'margin-top:4px;margin-right:12px;align-self:stretch;"></div>'
                    f'<div style="font-size:14px;color:#2a1a10;line-height:1.55;">{inline(item)}</div>'
                    '</div>'
                )
            return out

        def render_section_body(body_lines: list[str]) -> str:
            out_parts: list[str] = []
            table_buf: list[str] = []
            bullet_buf: list[str] = []
            para_buf: list[str] = []

            def flush_table() -> None:
                if table_buf:
                    out_parts.append(render_table(parse_table_lines(table_buf)))
                    table_buf.clear()

            def flush_bullets() -> None:
                if bullet_buf:
                    out_parts.append(render_bullets(bullet_buf))
                    bullet_buf.clear()

            def flush_para() -> None:
                if para_buf:
                    joined = " ".join(para_buf).strip()
                    if joined:
                        out_parts.append(
                            f'<p style="margin:5px 0 8px;font-size:14px;color:#2a1a10;'
                            f'line-height:1.65;">{inline(joined)}</p>')
                    para_buf.clear()

            for ln in body_lines:
                s = ln.strip()
                if not s:
                    flush_para()
                    continue
                if s.startswith("|"):
                    flush_bullets(); flush_para()
                    table_buf.append(s)
                elif s.startswith("- "):
                    flush_table(); flush_para()
                    bullet_buf.append(s[2:])
                else:
                    flush_table(); flush_bullets()
                    para_buf.append(s)

            flush_table(); flush_bullets(); flush_para()
            return "".join(out_parts)

        # ── Parse title, tape callout, body lines ─────────────────────────────
        title = "Peach Brief"
        tape = ""
        body_lines: list[str] = []

        for ln in text.splitlines():
            if ln.startswith("# "):
                title = ln[2:].strip()
            elif ln.startswith("> "):
                tape = ln[2:].strip()
            else:
                body_lines.append(ln)

        # Split body into sections on ---
        raw_sections: list[list[str]] = []
        current: list[str] = []
        for ln in body_lines:
            if ln.strip() == "---":
                if any(l.strip() for l in current):
                    raw_sections.append(current)
                current = []
            else:
                current.append(ln)
        if any(l.strip() for l in current):
            raw_sections.append(current)

        # ── Extract % changes for the bar chart ───────────────────────────────
        chart_data: list[tuple[str, float]] = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 3:
                continue
            m_pct = re.search(r'(↑|↓)\s*([\d.]+)%', cells[-1])
            if m_pct and re.match(r'^[A-Z]{2,5}$', cells[0]):
                sign = -1 if m_pct.group(1) == "↓" else 1
                chart_data.append((cells[0], sign * float(m_pct.group(2))))

        def build_chart_svg(data: list[tuple[str, float]]) -> str:
            if not data:
                return ""
            row_h, label_w, bar_max_w, pad = 28, 52, 200, 16
            total_h = len(data) * row_h + pad * 2
            total_w = 560
            mid_x = label_w + bar_max_w  # zero line x

            max_abs = max(abs(v) for _, v in data) or 1
            svg = (f'<svg width="{total_w}" height="{total_h}" '
                   f'xmlns="http://www.w3.org/2000/svg" '
                   f'style="display:block;width:100%;max-width:{total_w}px;">')

            # background
            svg += f'<rect width="{total_w}" height="{total_h}" fill="#fff7f2" rx="6"/>'

            # zero line
            svg += (f'<line x1="{mid_x}" y1="{pad//2}" x2="{mid_x}" '
                    f'y2="{total_h - pad//2}" stroke="#f0d8c8" stroke-width="1"/>')

            for i, (ticker, pct) in enumerate(data):
                y = pad + i * row_h
                bar_w = int(abs(pct) / max_abs * bar_max_w * 0.88)
                bar_color = "#4cae78" if pct >= 0 else "#e07840"
                bar_x = mid_x if pct >= 0 else mid_x - bar_w
                cy = y + row_h // 2

                # ticker label
                svg += (f'<text x="{label_w - 8}" y="{cy + 4}" '
                        f'font-family="-apple-system,BlinkMacSystemFont,\'Segoe UI\',Arial,sans-serif" '
                        f'font-size="12" font-weight="600" fill="#2a1a10" '
                        f'text-anchor="end">{ticker}</text>')

                # bar
                if bar_w > 0:
                    svg += (f'<rect x="{bar_x}" y="{cy - 7}" width="{bar_w}" height="14" '
                            f'rx="3" fill="{bar_color}" opacity="0.88"/>')

                # % label
                sign_str = "+" if pct > 0 else ""
                label_x = (mid_x + bar_w + 6) if pct >= 0 else (mid_x - bar_w - 6)
                anchor = "start" if pct >= 0 else "end"
                svg += (f'<text x="{label_x}" y="{cy + 4}" '
                        f'font-family="-apple-system,BlinkMacSystemFont,\'Segoe UI\',Arial,sans-serif" '
                        f'font-size="11" fill="{bar_color}" font-weight="600" '
                        f'text-anchor="{anchor}">{sign_str}{pct:.2f}%</text>')

            svg += "</svg>"
            return svg

        chart_svg = build_chart_svg(chart_data)
        chart_block = ""
        if chart_svg:
            chart_block = (
                '<div style="padding:16px 24px 12px;border-bottom:1px solid #fae0cc;">'
                '<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
                'text-transform:uppercase;color:#c05818;margin-bottom:10px;">Market Snapshot</div>'
                + chart_svg +
                '</div>'
            )

        # ── Tape callout ──────────────────────────────────────────────────────
        tape_html = ""
        if tape:
            m = re.match(r'^(RISK-ON|RISK-OFF|MIXED)(.*)', tape)
            if m:
                tag, rest = m.group(1), m.group(2).lstrip(" —-").strip()
                tag_styles = {
                    "RISK-ON":  ("#16a34a", "#edfbf3", "#c8f0da"),
                    "RISK-OFF": ("#dc2626", "#fef2f2", "#fdd8d8"),
                    "MIXED":    ("#c05818", "#fff4ee", "#fddcc8"),
                }
                clr, bg, border_bg = tag_styles.get(tag, ("#c05818", "#fff4ee", "#fddcc8"))
                tape_html = (
                    f'<div style="background:{bg};border-left:4px solid {clr};'
                    f'padding:14px 24px;">'
                    f'<span style="font-size:11px;font-weight:700;color:{clr};'
                    f'letter-spacing:0.08em;text-transform:uppercase;'
                    f'background:{border_bg};padding:2px 8px;border-radius:20px;'
                    f'margin-right:8px;">{tag}</span>'
                    f'<span style="font-size:14px;color:#3a2010;">{inline(rest)}</span>'
                    f'</div>')
            else:
                tape_html = (
                    f'<div style="background:#fff4ee;border-left:4px solid #c05818;'
                    f'padding:14px 24px;">'
                    f'<span style="font-size:14px;color:#3a2010;">{inline(tape)}</span>'
                    f'</div>')

        # ── Render sections ───────────────────────────────────────────────────
        sections_html = ""
        for sec in raw_sections:
            stripped = [l for l in sec if l.strip()]
            if not stripped:
                continue

            first = stripped[0].strip()
            hdr_m = re.match(r'^\*\*(.+?)\*\*\s*(.*)', first)
            hdr = ""
            body_start = stripped

            if hdr_m and not first.startswith("|") and not first.startswith("-"):
                hdr = hdr_m.group(1)
                leftover = hdr_m.group(2).strip()
                body_start = ([leftover] if leftover else []) + stripped[1:]

            if hdr.startswith("Today"):
                focus_text = " ".join(body_start).strip().lstrip("— ").strip()
                sections_html += (
                    '<div style="padding:20px 24px;background:linear-gradient(135deg,#fff4ee,#fde8d8);">'
                    '<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
                    'text-transform:uppercase;color:#c05818;margin-bottom:8px;">'
                    "&#x1F351; Today&#x2019;s Focus</div>"
                    f'<p style="margin:0;font-size:15px;font-weight:500;color:#1c0804;'
                    f'line-height:1.6;">{inline(focus_text)}</p>'
                    '</div>')
                continue

            hdr_html = ""
            if hdr:
                hdr_html = (
                    f'<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
                    f'text-transform:uppercase;color:#c05818;margin-bottom:10px;">'
                    f'{html.escape(hdr)}</div>')

            body_html = render_section_body(body_start)
            if hdr_html or body_html:
                sections_html += (
                    '<div style="padding:18px 24px;border-bottom:1px solid #fae0cc;">'
                    f'{hdr_html}{body_html}</div>')

        # ── SVG wave separator (static, decorative) ───────────────────────────
        wave_svg = (
            '<svg viewBox="0 0 600 32" xmlns="http://www.w3.org/2000/svg" '
            'style="display:block;width:100%;margin-bottom:-1px;" preserveAspectRatio="none">'
            '<path d="M0,16 C80,32 160,0 240,16 C320,32 400,0 480,16 C530,26 565,10 600,16 '
            'L600,32 L0,32 Z" fill="#fff7f2"/>'
            '<path d="M0,22 C100,10 200,30 300,20 C400,10 500,28 600,18 '
            'L600,32 L0,32 Z" fill="#ffffff" opacity="0.5"/>'
            '</svg>'
        )

        # ── CSS animation (works in Apple Mail, Gmail apps, degrades elsewhere) ─
        anim_css = """<style>
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.peach-card{animation:fadeUp 0.5s ease both}
.peach-s1{animation-delay:0.05s}.peach-s2{animation-delay:0.12s}
.peach-s3{animation-delay:0.19s}.peach-s4{animation-delay:0.26s}
</style>"""

        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  {anim_css}
</head>
<body style="margin:0;padding:20px 0 32px;background:linear-gradient(160deg,#fdf0e8 0%,#f5e4d4 100%);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <div style="max-width:600px;margin:0 auto;">

    <!-- Header card -->
    <div class="peach-card peach-s1" style="background:linear-gradient(135deg,#ffe8d0 0%,#fdd0a8 45%,#f8b888 100%);border-radius:14px 14px 0 0;padding:28px 28px 0;position:relative;overflow:hidden;">
      <!-- decorative orb -->
      <div style="position:absolute;top:-40px;right:-40px;width:160px;height:160px;background:rgba(255,255,255,0.18);border-radius:50%;"></div>
      <div style="position:absolute;top:10px;right:30px;width:80px;height:80px;background:rgba(255,255,255,0.12);border-radius:50%;"></div>
      <div style="font-size:11px;letter-spacing:0.10em;text-transform:uppercase;color:#9c5c2c;margin-bottom:7px;position:relative;">Peach &middot; Pre-Market Intelligence</div>
      <h1 style="margin:0 0 20px;font-size:26px;font-weight:700;color:#2a1208;letter-spacing:-0.3px;position:relative;">{html.escape(title)}</h1>
      {wave_svg}
    </div>

    <!-- Main content card -->
    <div class="peach-card peach-s2" style="background:#ffffff;border-radius:0 0 14px 14px;overflow:hidden;box-shadow:0 4px 24px rgba(180,100,40,0.12);">
      {tape_html}
      {chart_block}
      {sections_html}
      <!-- Footer -->
      <div style="padding:14px 24px;background:#fdf8f4;border-top:1px solid #fae0cc;">
        <p style="margin:0;font-size:11px;color:#b09080;">Peach &middot; Pre-market intelligence, automated &middot; Not financial advice</p>
      </div>
    </div>

  </div>
</body>
</html>"""
