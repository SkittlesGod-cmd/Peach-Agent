"""Agentic loop for the research opportunity hunter."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import requests

from .config import PeachConfig
from .research_db import ResearchDB
from .research_tools import TOOL_SCHEMAS, TARGET_UNIVERSITIES, SUBFIELDS, ResearchToolExecutor

_SYSTEM = """\
You are Peach, a research opportunity hunting agent for {name}, a {grade} high school student \
on a pre-med track with a deep interest in neurosurgery and neuroscience research.

Student profile:
  Name:      {name}
  Grade:     {grade}
  GPA:       {gpa}
  Courses:   {courses}
  Skills:    {skills}
  Interests: {interests}
  Email:     {student_email}

═══ YOUR JOB ════════════════════════════════════════════════════════════════════

1. Find professors at top universities doing neuroscience / neurosurgery research.
2. Use web_search to find REAL faculty pages — do not invent names or emails.
3. Use scrape_lab_page to read their page and extract their email and recent work.
4. Call add_professor to save each one.
5. If scrape_lab_page found a real email, send a personalized email with send_outreach_email.
6. On follow-up runs, use get_followups_due + send_followup_email.

═══ WEB SEARCH STRATEGY ════════════════════════════════════════════════════════

For each university + subfield combination, run searches like:
  • "[University] [subfield] professor faculty research lab"
  • "[University] neurosurgery department faculty site:[university domain]"
  • "[University] [subfield] lab PI email contact"

Look for faculty directory pages, individual lab pages, and department pages.
Scrape the most promising URLs to find professor names, emails, and recent work.

═══ EMAIL RULES (strictly enforced) ════════════════════════════════════════════

• Under 200 words. No exceptions.
• Reference ONE specific paper or research project by exact name — never generic praise.
• State clearly: high school student seeking a summer research position.
• Mention 1-2 concrete skills or courses relevant to their specific work.
• Close with: "I would welcome the opportunity to speak with you about your work."
• Sign: {name}
• NEVER fabricate or guess email addresses. Only email if scrape_lab_page returned it.
• If no email found on the page, add the professor as "found" status without emailing.

═══ QUALITY BAR ═════════════════════════════════════════════════════════════════

A good outreach email:
  ✓ Opens by naming their lab or a specific publication
  ✓ In one sentence explains what specifically interests you about it
  ✓ States your background concisely (grade, GPA, relevant coursework/skills)
  ✓ Makes a clear, specific ask for summer research
  ✓ Stays under 200 words, is warm but professional
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
        existing = {(p["name"], p["university"]) for p in self.db.get_all()}

        # Pick universities not yet fully covered
        covered = {p["university"] for p in self.db.get_all()}
        remaining = [u for u in TARGET_UNIVERSITIES if u not in covered]
        if not remaining:
            remaining = TARGET_UNIVERSITIES  # all done once, loop back

        unis = remaining[:batch]
        subfields = random.sample(SUBFIELDS, min(3, len(SUBFIELDS)))

        prompt = (
            f"Hunt for neuroscience and neurosurgery research opportunities at these universities:\n"
            f"{chr(10).join(f'  • {u}' for u in unis)}\n\n"
            f"Focus subfields (vary across universities):\n"
            f"{chr(10).join(f'  • {s}' for s in subfields)}\n\n"
            f"For each university:\n"
            f"1. Call web_search with a query to find their neuroscience/neurosurgery faculty.\n"
            f"   Try queries like '[University] neurosurgery faculty lab' and "
            f"   '[University] neuroscience department professors research'.\n"
            f"2. From the search results, pick the 2-3 most promising faculty profile URLs.\n"
            f"3. Call scrape_lab_page on each URL.\n"
            f"4. Call add_professor for each real professor found.\n"
            f"5. If scrape_lab_page returned an email, send a personalized outreach email.\n\n"
            f"Already in database (skip): "
            f"{', '.join(f'{n} ({u})' for n, u in list(existing)[:15]) or 'none yet'}.\n\n"
            f"Be thorough — try multiple search queries per university if the first one "
            f"doesn't yield professor pages."
        )
        result = self._run_loop(prompt)
        self.sync_dashboard()
        return result

    def run_followups(self) -> str:
        """Send follow-up emails to professors who haven't replied in 14+ days."""
        result = self._run_loop(
            "Check for professors needing a follow-up using get_followups_due.\n"
            "For each one returned:\n"
            "1. Draft a brief, polite follow-up (3-4 sentences max).\n"
            "2. Remind them of your earlier email and reiterate your interest.\n"
            "3. Send it with send_followup_email.\n"
            "Do not follow up with anyone already marked 'followed_up' — only 'emailed' status."
        )
        self.sync_dashboard()
        return result

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
                timeout=20,
            )
            resp.raise_for_status()
            self.logger.info("Research dashboard synced ✓")
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

    def _run_loop(self, user_content: str, max_iter: int = 20) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": user_content},
        ]

        for iteration in range(max_iter):
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
                    self.logger.debug("[%d] Tool %s → %s", iteration, fn["name"], str(result)[:300])
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
                        "temperature": 0.2,
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
                    wait = 2 ** attempt * 3
                    self.logger.warning("LLM call failed (attempt %d): %s — retrying in %ds", attempt + 1, exc, wait)
                    time.sleep(wait)
                    continue
                raise
        return {}
