"""Tools and executor for the research opportunity hunting agent."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

import requests

from .config import PeachConfig
from .research_db import Professor, ResearchDB

TARGET_UNIVERSITIES = [
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
]

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_professors",
            "description": (
                "Search for professors at a specific university doing neuroscience or "
                "neurosurgery research. Returns a list of candidate professors with names, "
                "departments, lab URLs, and research focus."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "university": {"type": "string", "description": "Full university name"},
                    "subfield": {
                        "type": "string",
                        "description": (
                            "Specific subfield: e.g. 'neurosurgery', 'computational neuroscience', "
                            "'brain tumor', 'spinal cord', 'neural engineering', 'neuroimaging'"
                        ),
                    },
                },
                "required": ["university", "subfield"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_lab_page",
            "description": "Fetch the text content of a professor's lab page or faculty profile URL.",
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
                    "email": {"type": "string", "description": "Only include if confirmed from lab page"},
                    "lab_url": {"type": "string"},
                    "research_focus": {"type": "string", "description": "2-sentence summary of their research"},
                    "recent_paper_title": {"type": "string"},
                    "recent_paper_summary": {"type": "string", "description": "1-sentence summary of the paper"},
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
                "Only call this if you have a confirmed email address from the lab page."
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
                            "Full email body — under 200 words, references their specific research, "
                            "mentions student background, clear ask for summer research position."
                        ),
                    },
                },
                "required": ["professor_id", "professor_name", "professor_email", "subject", "body"],
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
            "description": "Return professors emailed 14+ days ago with no reply — ready for a follow-up.",
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
                    "body": {"type": "string"},
                },
                "required": ["professor_id", "professor_name", "professor_email", "body"],
            },
        },
    },
]

_UNI_DOMAINS: dict[str, str] = {
    "johns hopkins": "jhu.edu",
    "stanford": "stanford.edu",
    "ucsf": "ucsf.edu",
    "columbia": "columbia.edu",
    "university of pennsylvania": "upenn.edu",
    "washington university": "wustl.edu",
    "duke": "duke.edu",
    "university of michigan": "umich.edu",
    "harvard": "harvard.edu",
    "yale": "yale.edu",
    "northwestern": "northwestern.edu",
    "uc san diego": "ucsd.edu",
    "ucsd": "ucsd.edu",
    "vanderbilt": "vanderbilt.edu",
    "emory": "emory.edu",
    "university of pittsburgh": "pitt.edu",
    "cornell": "cornell.edu",
    "nyu": "nyu.edu",
    "mount sinai": "mssm.edu",
    "university of chicago": "uchicago.edu",
    "mayo clinic": "mayo.edu",
}


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

    def execute(self, name: str, args: dict[str, Any]) -> str:
        dispatch = {
            "search_professors": self._search_professors,
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

    def _search_professors(self, university: str, subfield: str) -> str:
        prompt = (
            f"List 4 real professors at {university} who actively research {subfield} "
            f"or related areas (neuroscience, neurosurgery, brain tumors, spinal cord, "
            f"neural engineering, neuroimaging, computational neuroscience). "
            f"For each give: name, department, lab URL (if known), email (if publicly listed), "
            f"and a 1-sentence description of their research focus. "
            f"Format as a JSON array with keys: name, department, lab_url, email, research_focus."
        )
        try:
            resp = self.session.post(
                self.config.proxy_url,
                json={
                    "model": self.config.openrouter_model,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "[]")
        except Exception as exc:
            return f"Search failed: {exc}"

    def _scrape_lab_page(self, url: str) -> str:
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (academic research inquiry)"},
                timeout=15,
            )
            r.raise_for_status()
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:3500]
        except Exception as exc:
            return f"Could not fetch {url}: {exc}"

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
            return json.dumps({"success": True, "professor_id": prof_id,
                               "message": f"Added {name} ({university})"})
        return json.dumps({"success": False,
                           "message": f"{name} at {university} already in database"})

    def _send_outreach_email(
        self,
        professor_id: int,
        professor_name: str,
        professor_email: str,
        subject: str,
        body: str,
    ) -> str:
        html_body = (
            f"<div style='font-family:Georgia,serif;font-size:15px;line-height:1.8;"
            f"color:#1a1a1a;max-width:600px;'>{body.replace(chr(10), '<br>')}</div>"
        )
        result = self._post_email(professor_email, subject, html_body)
        if result.get("id"):
            self.db.log_outreach(professor_id, "email", subject, body)
            self.db.update_status(professor_id, "emailed")
            self.logger.info("Outreach sent → %s (%s)", professor_name, professor_email)
            return json.dumps({"success": True, "message": f"Email sent to {professor_name}"})
        return json.dumps({"success": False, "error": result.get("error", "unknown")})

    def _list_professors(self, status: str | None = None) -> str:
        profs = self.db.get_all(status)
        if not profs:
            label = f" with status '{status}'" if status else ""
            return f"No professors found{label}."
        return json.dumps(profs[:25])

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
        subject = f"Following up — Research Inquiry"
        html_body = (
            f"<div style='font-family:Georgia,serif;font-size:15px;line-height:1.8;"
            f"color:#1a1a1a;max-width:600px;'>{body.replace(chr(10), '<br>')}</div>"
        )
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
            resp = requests.post(url, json={"to": to, "subject": subject, "html": html}, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"error": str(exc)}
