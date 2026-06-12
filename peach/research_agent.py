"""Agentic loop for the research opportunity hunter."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from .config import PeachConfig
from .research_db import ResearchDB
from .research_tools import TOOL_SCHEMAS, TARGET_UNIVERSITIES, ResearchToolExecutor

_SYSTEM = """\
You are Peach, a research opportunity hunting agent for {name}, a {grade} high school student \
on a pre-med track with a strong interest in neurosurgery and neuroscience research.

Student profile:
  Name:     {name}
  Grade:    {grade}
  GPA:      {gpa}
  Courses:  {courses}
  Skills:   {skills}
  Interests: {interests}
  Email:    {student_email}

Your job:
1. Find professors at top universities doing neuroscience / neurosurgery research.
2. Save each one with add_professor.
3. If you find a confirmed public email on their lab page, draft and send a personalized \
cold email with send_outreach_email.
4. On follow-up runs, use get_followups_due + send_followup_email.

Email rules (strictly enforced):
- Under 200 words.
- Reference ONE specific paper or project by name — never generic praise.
- State clearly: high school student, seeking summer research position.
- Mention 1-2 concrete skills or courses relevant to their work.
- Close: "I would welcome the opportunity to speak with you about your work."
- Sign: {name}
- Do NOT fabricate email addresses. Only email if you found the address on their lab page.
"""


class ResearchAgent:
    def __init__(
        self,
        config: PeachConfig,
        db: ResearchDB,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.logger = logger or logging.getLogger("peach.research")
        self.executor = ResearchToolExecutor(config, db, logger)
        self.session = requests.Session()

    # ── Public entry points ────────────────────────────────────────────────────

    def run_hunt(self, batch: int = 3) -> str:
        """Hunt for new professors across a batch of universities."""
        unis = TARGET_UNIVERSITIES[:batch]
        existing = {(p["name"], p["university"]) for p in self.db.get_all()}
        prompt = (
            f"Hunt for neuroscience and neurosurgery research opportunities at these universities: "
            f"{', '.join(unis)}.\n\n"
            f"For each university:\n"
            f"1. Call search_professors with a relevant subfield.\n"
            f"2. If you get a lab_url, call scrape_lab_page to get their email and recent work.\n"
            f"3. Call add_professor for each one found.\n"
            f"4. If you confirmed their email from the lab page, draft and send a personalized "
            f"outreach email with send_outreach_email.\n\n"
            f"Focus subfields: neurosurgery, brain tumor, spinal cord injury, computational "
            f"neuroscience, neuroimaging, neural engineering.\n"
            f"Already in database (skip these): "
            f"{', '.join(f'{n} ({u})' for n, u in list(existing)[:10]) or 'none yet'}."
        )
        return self._run_loop(prompt)

    def run_followups(self) -> str:
        """Send follow-up emails to professors who haven't replied in 14+ days."""
        return self._run_loop(
            "Check for professors needing follow-up using get_followups_due. "
            "For each one, draft a brief, polite follow-up (3-4 sentences) and send it "
            "with send_followup_email. Do not follow up more than once per professor."
        )

    def sync_dashboard(self) -> bool:
        """Push a JSON snapshot to the Vercel dashboard endpoint."""
        token = self.config.research_sync_token
        if not token:
            self.logger.debug("No research_sync_token — skipping dashboard sync")
            return False
        base = self.config.proxy_url.rsplit("/api/", 1)[0]
        url = f"{base}/api/research-sync"
        try:
            resp = requests.post(
                url,
                json=self.db.snapshot(),
                headers={"x-sync-token": token, "Content-Type": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            self.logger.info("Research dashboard synced")
            return True
        except Exception as exc:
            self.logger.warning("Dashboard sync failed: %s", exc)
            return False

    # ── Internal ───────────────────────────────────────────────────────────────

    def _system_prompt(self) -> str:
        p = self.config.student_profile
        return _SYSTEM.format(
            name=p.get("name", "Svanik"),
            grade=p.get("grade", "11th grade"),
            gpa=p.get("gpa", "4.0"),
            courses=p.get("courses", "AP Biology, AP Chemistry, AP Computer Science"),
            skills=p.get("skills", "Python, data analysis, literature review"),
            interests=p.get("interests", "neurosurgery, neuroscience, pre-med research"),
            student_email=p.get("email", self.config.email_to or ""),
        )

    def _run_loop(self, user_content: str, max_iter: int = 14) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": user_content},
        ]

        for _ in range(max_iter):
            response = self._call_llm(messages)
            choice = response.get("choices", [{}])[0]
            msg = choice.get("message", {})
            finish = choice.get("finish_reason", "stop")
            messages.append(msg)

            if finish == "tool_calls" and msg.get("tool_calls"):
                for call in msg["tool_calls"]:
                    fn = call["function"]
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    result = self.executor.execute(fn["name"], args)
                    self.logger.debug("Tool %s → %s", fn["name"], str(result)[:200])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result,
                    })
                continue

            return str(msg.get("content", "")).strip()

        return "Research run completed (max iterations reached)."

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        for attempt in range(3):
            try:
                resp = self.session.post(
                    self.config.proxy_url,
                    json={
                        "model": self.config.openrouter_model,
                        "temperature": 0.3,
                        "messages": messages,
                        "tools": TOOL_SCHEMAS,
                        "tool_choice": "auto",
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise
        return {}
