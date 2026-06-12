"""Tools and executor for the research opportunity hunting agent."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import datetime
from typing import Any

import requests

from .config import PeachConfig
from .research_db import Professor, ResearchDB

TARGET_UNIVERSITIES = [
    # Elite neuroscience / neurosurgery programs
    "Johns Hopkins University",
    "Stanford University",
    "UCSF",
    "Columbia University",
    "University of Pennsylvania",
    "Washington University in St. Louis",
    "Duke University",
    "University of Michigan",
    "Harvard University",
    "Yale University",
    "Mayo Clinic",
    "Vanderbilt University",
    "Northwestern University",
    "UC San Diego",
    "Emory University",
    "University of Pittsburgh",
    "Cornell University",
    "NYU Langone",
    "Mount Sinai",
    "University of Chicago",
    # Expanded nationwide coverage
    "UCLA",
    "UC Berkeley",
    "University of Texas Southwestern",
    "University of Washington",
    "University of Wisconsin-Madison",
    "University of Minnesota",
    "Ohio State University",
    "University of Florida",
    "Baylor College of Medicine",
    "University of Rochester",
    "Brown University",
    "Dartmouth College",
    "Georgetown University",
    "University of Virginia",
    "University of North Carolina Chapel Hill",
    "University of Colorado Denver",
    "University of Iowa",
    "Boston University",
    "Tufts University",
    "Thomas Jefferson University",
    "Temple University Hospital",
    "University of Miami",
    "University of Arizona",
    "Penn State College of Medicine",
    "Indiana University School of Medicine",
]

SUBFIELDS = [
    "neurosurgery",
    "brain tumor glioblastoma",
    "spinal cord injury",
    "computational neuroscience",
    "neuroimaging fMRI",
    "neural engineering brain computer interface",
    "neurodegenerative Alzheimer Parkinson",
    "pediatric neurology",
    "cerebrovascular stroke",
    "neuro-oncology",
]

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for real, up-to-date information. Use this to find "
                "faculty directory pages, professor lab pages, and contact information. "
                "Returns titles, URLs, and snippets from top results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query. For finding professors use queries like: "
                            "'Stanford neurosurgery professor faculty lab site:stanford.edu' or "
                            "'Johns Hopkins brain tumor research professor email'"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_lab_page",
            "description": (
                "Fetch a professor's lab page or faculty profile. Extracts text content "
                "AND any email addresses found on the page. Always scrape before adding "
                "a professor so you have their confirmed email."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_professor",
            "description": "Save a discovered professor to the research database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "university": {"type": "string"},
                    "department": {"type": "string"},
                    "email": {
                        "type": "string",
                        "description": "Only include if confirmed from their lab page via scrape_lab_page",
                    },
                    "lab_url": {"type": "string"},
                    "research_focus": {
                        "type": "string",
                        "description": "2-sentence summary of their research",
                    },
                    "recent_paper_title": {"type": "string"},
                    "recent_paper_summary": {
                        "type": "string",
                        "description": "1-sentence summary of the paper",
                    },
                },
                "required": ["name", "university", "research_focus"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_outreach_email",
            "description": (
                "Send a personalized cold email to a professor requesting a research position. "
                "ONLY call this if you confirmed the email address from scrape_lab_page. "
                "Never fabricate or guess an email address."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "professor_id": {"type": "integer"},
                    "professor_name": {"type": "string"},
                    "professor_email": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {
                        "type": "string",
                        "description": (
                            "Full email body — under 200 words. Must reference ONE specific "
                            "paper or project by name. State: high school student, seeking "
                            "summer research position. Mention 1-2 concrete relevant skills."
                        ),
                    },
                },
                "required": [
                    "professor_id",
                    "professor_name",
                    "professor_email",
                    "subject",
                    "body",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_professors",
            "description": "List professors in the database, optionally filtered by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["found", "emailed", "followed_up", "replied", "declined"],
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_followups_due",
            "description": "Return professors emailed 14+ days ago with no reply — ready for follow-up.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_followup_email",
            "description": "Send a polite follow-up email to a professor who hasn't replied.",
            "parameters": {
                "type": "object",
                "properties": {
                    "professor_id": {"type": "integer"},
                    "professor_name": {"type": "string"},
                    "professor_email": {"type": "string"},
                    "body": {
                        "type": "string",
                        "description": "Brief follow-up, 3-4 sentences max.",
                    },
                },
                "required": ["professor_id", "professor_name", "professor_email", "body"],
            },
        },
    },
]

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
_SKIP_EMAIL_PATTERNS = [
    "noreply", "no-reply", "webmaster", "admin@", "support@",
    "info@example", "contact@example", "example.com", "test@",
    "donotreply", "do-not-reply", "@w3", "schema.org",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _clean_emails(raw: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for e in raw:
        e = e.lower().strip(".,;")
        if e in seen:
            continue
        if any(skip in e for skip in _SKIP_EMAIL_PATTERNS):
            continue
        seen.add(e)
        out.append(e)
    return out[:8]


class ResearchToolExecutor:
    def __init__(
        self,
        config: PeachConfig,
        db: ResearchDB,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.logger = logger or logging.getLogger("peach.research")
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def execute(self, name: str, args: dict[str, Any]) -> str:
        dispatch = {
            "web_search": self._web_search,
            "scrape_lab_page": self._scrape_lab_page,
            "add_professor": self._add_professor,
            "send_outreach_email": self._send_outreach_email,
            "list_professors": self._list_professors,
            "get_followups_due": self._get_followups_due,
            "send_followup_email": self._send_followup_email,
        }
        fn = dispatch.get(name)
        if not fn:
            return f"Unknown tool: {name}"
        try:
            return fn(**args)
        except Exception as exc:
            self.logger.exception("Tool %s failed: %s", name, exc)
            return f"Error in {name}: {exc}"

    # ── Tool implementations ───────────────────────────────────────────────────

    def _web_search(self, query: str) -> str:
        """Search DuckDuckGo HTML and return top results with titles, URLs, snippets."""
        try:
            url = "https://html.duckduckgo.com/html/"
            r = self.session.get(
                url,
                params={"q": query, "kl": "us-en"},
                timeout=20,
            )
            r.raise_for_status()
            html = r.text

            # Extract result links — DDG wraps them in class="result__a"
            link_pattern = re.compile(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                re.DOTALL,
            )
            snippet_pattern = re.compile(
                r'class="result__snippet"[^>]*>(.*?)</a>',
                re.DOTALL,
            )

            links = link_pattern.findall(html)
            snippets = [re.sub(r"<[^>]+>", "", s).strip() for s in snippet_pattern.findall(html)]

            results = []
            for i, (href, title) in enumerate(links[:8]):
                title_clean = re.sub(r"<[^>]+>", "", title).strip()
                snippet = snippets[i] if i < len(snippets) else ""
                # DDG sometimes wraps hrefs in redirect URLs — try to unwrap
                if "uddg=" in href:
                    inner = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [""])
                    href = urllib.parse.unquote(inner[0]) if inner[0] else href
                results.append({"title": title_clean, "url": href, "snippet": snippet})

            if not results:
                return json.dumps({"error": "No results found", "query": query})
            return json.dumps(results)
        except Exception as exc:
            return json.dumps({"error": str(exc), "query": query})

    def _scrape_lab_page(self, url: str) -> str:
        """Fetch a lab/faculty page. Returns text content + all emails found on the page."""
        try:
            r = self.session.get(url, timeout=20)
            r.raise_for_status()
            html = r.text

            # Extract emails from raw HTML before stripping tags
            raw_emails = _EMAIL_RE.findall(html)
            emails = _clean_emails(raw_emails)

            # Strip tags and normalise whitespace
            text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

            return json.dumps({
                "url": url,
                "emails_found": emails,
                "content": text[:3500],
            })
        except Exception as exc:
            return json.dumps({"error": str(exc), "url": url})

    def _add_professor(
        self,
        name: str,
        university: str,
        research_focus: str,
        department: str = "",
        email: str | None = None,
        lab_url: str | None = None,
        recent_paper_title: str | None = None,
        recent_paper_summary: str | None = None,
    ) -> str:
        prof = Professor(
            name=name,
            university=university,
            department=department,
            email=email,
            lab_url=lab_url,
            research_focus=research_focus,
            recent_paper_title=recent_paper_title,
            recent_paper_summary=recent_paper_summary,
        )
        prof_id = self.db.add_professor(prof)
        if prof_id:
            return json.dumps({
                "success": True,
                "professor_id": prof_id,
                "message": f"Added {name} ({university})",
            })
        return json.dumps({
            "success": False,
            "message": f"{name} at {university} already in database",
        })

    def _send_outreach_email(
        self,
        professor_id: int,
        professor_name: str,
        professor_email: str,
        subject: str,
        body: str,
    ) -> str:
        html_body = _format_outreach_html(body)
        result = self._post_email(professor_email, subject, html_body)
        if result.get("id"):
            self.db.log_outreach(professor_id, "email", subject, body)
            self.db.update_status(professor_id, "emailed")
            self.logger.info("Outreach sent → %s <%s>", professor_name, professor_email)
            return json.dumps({"success": True, "message": f"Email sent to {professor_name}"})
        return json.dumps({"success": False, "error": result.get("error", "unknown")})

    def _list_professors(self, status: str | None = None) -> str:
        profs = self.db.get_all(status)
        if not profs:
            label = f" with status '{status}'" if status else ""
            return f"No professors found{label}."
        return json.dumps(profs[:30])

    def _get_followups_due(self) -> str:
        profs = self.db.get_followup_due()
        if not profs:
            return "No follow-ups due."
        return json.dumps(profs)

    def _send_followup_email(
        self,
        professor_id: int,
        professor_name: str,
        professor_email: str,
        body: str,
    ) -> str:
        subject = "Following up — Research Inquiry"
        html_body = _format_outreach_html(body)
        result = self._post_email(professor_email, subject, html_body)
        if result.get("id"):
            self.db.log_outreach(professor_id, "followup", subject, body)
            self.db.update_status(professor_id, "followed_up")
            return json.dumps({"success": True, "message": f"Follow-up sent to {professor_name}"})
        return json.dumps({"success": False, "error": result.get("error", "unknown")})

    def _post_email(self, to: str, subject: str, html: str) -> dict:
        base = self.config.proxy_url.rsplit("/api/", 1)[0]
        url = f"{base}/api/send-email"
        try:
            resp = requests.post(
                url,
                json={"to": to, "subject": subject, "html": html},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"error": str(exc)}


def _format_outreach_html(body: str) -> str:
    """Wrap plain-text email body in clean Georgia serif HTML."""
    paragraphs = []
    for para in body.strip().split("\n\n"):
        lines = para.strip().replace("\n", "<br>")
        paragraphs.append(f"<p style='margin:0 0 16px 0'>{lines}</p>")
    inner = "\n".join(paragraphs)
    return (
        "<div style='"
        "font-family:Georgia,\"Times New Roman\",Times,serif;"
        "font-size:15px;line-height:1.8;color:#1a1a1a;max-width:600px;"
        "margin:0 auto;padding:24px 0;"
        "'>"
        f"{inner}"
        "</div>"
    )
