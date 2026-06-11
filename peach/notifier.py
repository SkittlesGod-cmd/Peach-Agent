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
    def _markdown_to_html(text: str) -> str:
        """Render the briefing as a styled HTML email with full inline styles (Gmail-safe)."""
        import re

        def inline(s: str) -> str:
            s = html.escape(s)
            s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
            s = re.sub(r'\b_(.+?)_\b', r'<em>\1</em>', s)
            s = re.sub(r'`(.+?)`',
                       r'<code style="background:#f5f0eb;padding:1px 5px;border-radius:3px;'
                       r'font-family:monospace;font-size:12px">\1</code>', s)
            return s

        def render_table(rows: list[list[str]]) -> str:
            if not rows:
                return ""
            out = ('<table style="width:100%;border-collapse:collapse;font-size:13px;'
                   'margin:10px 0;">')
            for i, row in enumerate(rows):
                bg = "#fdf5ef" if i == 0 else ("#ffffff" if i % 2 == 0 else "#fef8f4")
                fw = "600" if i == 0 else "400"
                out += f'<tr style="background:{bg};">'
                for cell in row:
                    out += (f'<td style="padding:7px 11px;border-bottom:1px solid #f0e4d8;'
                            f'font-weight:{fw};color:#2a1a10;white-space:nowrap;">'
                            f'{inline(cell)}</td>')
                out += "</tr>"
            out += "</table>"
            return out

        def render_bullets(items: list[str]) -> str:
            out = '<table style="width:100%;border-collapse:collapse;margin:6px 0;">'
            for item in items:
                out += ('<tr><td style="width:4px;background:#e0784c;border-radius:2px;'
                        'padding:0;"></td>'
                        '<td style="padding:6px 0 6px 12px;font-size:14px;color:#2a1a10;'
                        f'line-height:1.55;">{inline(item)}</td></tr>')
            out += "</table>"
            return out

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
                            f'<p style="margin:5px 0;font-size:14px;color:#2a1a10;'
                            f'line-height:1.6;">{inline(joined)}</p>')
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

        # ── Parse title, tape, sections ──────────────────────────────────────
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

        # Split into sections on ---
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

        # ── Tape callout ─────────────────────────────────────────────────────
        tape_html = ""
        if tape:
            m = re.match(r'^(RISK-ON|RISK-OFF|MIXED)(.*)', tape)
            if m:
                tag, rest = m.group(1), m.group(2).lstrip(" —-").strip()
                colors = {"RISK-ON": ("#16a34a", "#f0fdf4"),
                          "RISK-OFF": ("#dc2626", "#fef2f2"),
                          "MIXED":    ("#c05818", "#fff7f0")}
                clr, bg = colors.get(tag, ("#c05818", "#fff7f0"))
                tape_html = (
                    f'<div style="background:{bg};border-left:4px solid {clr};'
                    f'padding:13px 24px;margin:0;">'
                    f'<span style="font-size:12px;font-weight:700;color:{clr};'
                    f'letter-spacing:0.07em;">{tag}</span>'
                    f'<span style="font-size:14px;color:#3a2010;"> — {inline(rest)}</span>'
                    f'</div>')
            else:
                tape_html = (
                    f'<div style="background:#fff7f0;border-left:4px solid #c05818;'
                    f'padding:13px 24px;">'
                    f'<span style="font-size:14px;color:#3a2010;">{inline(tape)}</span>'
                    f'</div>')

        # ── Render each section ───────────────────────────────────────────────
        sections_html = ""
        for sec in raw_sections:
            stripped = [l for l in sec if l.strip()]
            if not stripped:
                continue

            # Extract section header (**Name**)
            first = stripped[0].strip()
            hdr_m = re.match(r'^\*\*(.+?)\*\*\s*(.*)', first)
            hdr = ""
            body_start = stripped

            if hdr_m and not first.startswith("|") and not first.startswith("-"):
                hdr = hdr_m.group(1)
                leftover = hdr_m.group(2).strip()
                body_start = ([leftover] if leftover else []) + stripped[1:]

            hdr_html = ""
            if hdr:
                # Today's Focus gets special treatment
                if hdr.startswith("Today"):
                    focus_text = " ".join(body_start).strip().lstrip("— ").strip()
                    sections_html += (
                        '<div style="padding:18px 24px;background:#fff7f0;'
                        'border-top:2px solid #e0784c;">'
                        '<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
                        'text-transform:uppercase;color:#c05818;margin-bottom:6px;">'
                        "Today's Focus</div>"
                        f'<p style="margin:0;font-size:15px;font-weight:500;color:#1c0804;'
                        f'line-height:1.55;">{inline(focus_text)}</p>'
                        '</div>')
                    continue
                hdr_html = (
                    f'<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
                    f'text-transform:uppercase;color:#c05818;margin-bottom:10px;">'
                    f'{html.escape(hdr)}</div>')

            body_html = render_section_body(body_start)
            if hdr_html or body_html:
                sections_html += (
                    f'<div style="padding:18px 24px;border-bottom:1px solid #f0e4d8;">'
                    f'{hdr_html}{body_html}</div>')

        return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:16px 0;background:#f0e8df;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.10);">
    <div style="background:linear-gradient(135deg,#1c0804 0%,#6a2010 45%,#c05818 100%);padding:26px 24px 20px;">
      <div style="font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:rgba(255,255,255,0.6);margin-bottom:6px;">Peach · Pre-Market Intelligence</div>
      <h1 style="margin:0;font-size:22px;font-weight:700;color:#ffffff;letter-spacing:-0.2px;">{html.escape(title)}</h1>
    </div>
    {tape_html}
    {sections_html}
    <div style="padding:14px 24px;background:#faf6f2;">
      <p style="margin:0;font-size:11px;color:#a09088;">Peach &middot; Pre-market intelligence, automated &middot; Not financial advice</p>
    </div>
  </div>
</body>
</html>"""
