"""Email notification engine for Peach."""

from __future__ import annotations

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import logging
import smtplib

from .config import PeachConfig


class EmailNotifier:
    def __init__(self, config: PeachConfig, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("peach")

    def send(self, markdown_report: str) -> None:
        if not self.config.has_email_settings:
            self._save_briefing(markdown_report)
            return

        subject = f"{self.config.email_subject_prefix} - {datetime.now().strftime('%Y-%m-%d')}"
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self.config.email_from or ""
        message["To"] = self.config.email_to or ""
        message.attach(MIMEText(markdown_report, "plain", "utf-8"))
        message.attach(MIMEText(self._markdown_to_html(markdown_report), "html", "utf-8"))

        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(self.config.smtp_username, self.config.smtp_password)
                smtp.send_message(message)
            self.logger.info("Sent Peach briefing email to %s", self.config.email_to)
        except smtplib.SMTPException as exc:
            self.logger.exception("SMTP transmission failed: %s", exc)
            raise
        except OSError as exc:
            self.logger.exception("Network error while sending email: %s", exc)
            raise

    def _save_briefing(self, markdown_report: str) -> None:
        path = self.config.home / "briefing.md"
        path.write_text(markdown_report, encoding="utf-8")
        self.logger.info("No email configured — briefing saved to %s", path)

    @staticmethod
    def _markdown_to_html(markdown_report: str) -> str:
        try:
            import markdown

            body = markdown.markdown(markdown_report, extensions=["extra", "sane_lists"])
        except ImportError:
            body = EmailNotifier._basic_markdown_to_html(markdown_report)

        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #202124; line-height: 1.55; }}
    h1, h2, h3 {{ color: #17202a; }}
    code {{ background: #f2f4f7; padding: 2px 4px; border-radius: 4px; }}
    a {{ color: #0b57d0; }}
  </style>
</head>
<body>{body}</body>
</html>"""

    @staticmethod
    def _basic_markdown_to_html(markdown_report: str) -> str:
        lines = markdown_report.splitlines()
        html_lines: list[str] = []
        in_list = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                continue

            if stripped.startswith("# "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h1>{html.escape(stripped[2:])}</h1>")
            elif stripped.startswith("## "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h2>{html.escape(stripped[3:])}</h2>")
            elif stripped.startswith("### "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h3>{html.escape(stripped[4:])}</h3>")
            elif stripped.startswith("- "):
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                html_lines.append(f"<li>{html.escape(stripped[2:])}</li>")
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<p>{html.escape(stripped)}</p>")

        if in_list:
            html_lines.append("</ul>")

        return "\n".join(html_lines)
