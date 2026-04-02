"""Agent loop — orchestrates the Planner → Executor → Evaluator cycle."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import ollama as ollama_lib

from agent.planner import Planner
from agent.executor import Executor
from agent.evaluator import Evaluator
from agent.prompts import SYSTEM_PROMPT
from memory.sqlite_store import SQLiteStore
from memory.faiss_retriever import FAISSRetriever
from tools import ToolRegistry
from tools.privacy import redact, restore, PrivacyResult

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Time detection — determines if user message contains a specific date/time
# --------------------------------------------------------------------------- #

import re as _re

_TIME_PATTERNS = [
    r"\b\d{1,2}:\d{2}\b",                           # 14:00, 2:30
    r"\b\d{1,2}\s*(?:am|pm)\b",                      # 2pm, 10 am
    r"\b(?:at|@)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",  # at 2pm, @ 3:00
    r"\b\d{4}-\d{2}-\d{2}\b",                        # 2026-02-10
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",                  # 02/10/2026
    r"\b(?:tomorrow|today)\s+(?:at\s+)?\d{1,2}",     # tomorrow at 3
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(?:at\s+)?\d{1,2}", # tuesday at 2
]
_TIME_RE = _re.compile("|".join(_TIME_PATTERNS), _re.IGNORECASE)


def _has_specific_time(text: str) -> bool:
    """Check if the user's message contains a specific date/time."""
    return bool(_TIME_RE.search(text))


class AgentLoop:
    """Top-level agent: NL input → plan → execute → evaluate → respond."""

    def __init__(self, cfg: dict, registry: ToolRegistry, db: SQLiteStore, faiss: FAISSRetriever):
        self._cfg = cfg
        self._model = cfg["agent"]["model"]
        self._client = ollama_lib

        self._planner = Planner(self._client, self._model, cfg["agent"].get("max_plan_steps", 10))
        self._executor = Executor(self._client, self._model, registry)
        self._evaluator = Evaluator(self._client, self._model, cfg["agent"].get("max_retries", 2))

        self._db = db
        self._faiss = faiss
        self._registry = registry
        self._session_id = uuid.uuid4().hex[:12]
        self._conversation: list[dict] = []
        self._buffer_size = cfg["agent"].get("conversation_buffer_size", 20)
        self._privacy_enabled: bool = True
        self._last_redacted_input: str = ""

        # CUMULATIVE entity map — survives across turns
        self._session_entity_map: dict[str, str] = {}

        # Files generated during the last run (reset each call)
        self._last_generated_files: list[dict] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def privacy_enabled(self) -> bool:
        return self._privacy_enabled

    @privacy_enabled.setter
    def privacy_enabled(self, value: bool):
        self._privacy_enabled = value

    @property
    def last_redacted_input(self) -> str:
        return self._last_redacted_input

    @property
    def last_generated_files(self) -> list[dict]:
        """Files generated during the last agent run."""
        return self._last_generated_files

    # ---- Public API ------------------------------------------------------ #

    def run(self, user_input: str, attachments: list[str] | None = None) -> str:
        logger.info("User: %s", user_input[:120])

        # Reset per-run state
        self._last_generated_files = []

        # 0. Handle attachments
        full_input = user_input
        if attachments:
            attachment_context = self._process_attachments(attachments)
            if attachment_context:
                full_input = f"{user_input}\n\n[Attached files context]\n{attachment_context}"

        # 1. Privacy — redact PII before the LLM sees the text
        privacy_result = redact(full_input, enabled=self._privacy_enabled)
        safe_input = privacy_result.redacted_text
        entity_map = privacy_result.entity_map

        # Merge new redactions into the cumulative session map
        if entity_map:
            self._session_entity_map.update(entity_map)
            logger.info("Privacy: redacted %d entities (%s engine), session total: %d",
                        len(entity_map), privacy_result.engine, len(self._session_entity_map))

        self._last_redacted_input = safe_input

        # 2. Save & buffer
        self._db.add_message(self._session_id, "user", user_input)
        self._conversation.append({"role": "user", "content": safe_input})
        self._trim_conversation()

        # 3. Context from memory
        context = self._build_context(safe_input)

        # 4. Plan
        steps = self._planner.plan(safe_input, context)
        logger.info("Plan (%d steps): %s", len(steps), steps)
        task_id = self._db.create_task(self._session_id, user_input, steps)
        self._db.update_task(task_id, "running")

        # 5. Execute each step — pass entity map so write-tools restore PII in files
        self._executor.set_entity_map(self._session_entity_map)

        # Detect if user provided a specific date/time for scheduling
        time_confirmed = _has_specific_time(user_input)
        self._executor.set_time_confirmed(time_confirmed)
        if time_confirmed:
            logger.info("Time detected in user input — scheduling allowed")
        else:
            logger.info("No specific time in user input — scheduling gate active")

        step_results: list[str] = []
        for i, step in enumerate(steps, 1):
            logger.info("Step %d/%d: %s", i, len(steps), step)
            result_text, self._conversation, step_files = self._executor.execute_step(
                step, self._conversation
            )
            self._last_generated_files.extend(step_files)

            eval_result = self._evaluator.evaluate(step, "executor", result_text[:1000])
            if not eval_result.success and eval_result.should_retry:
                logger.warning("Step %d failed — retrying: %s", i, eval_result.reason)
                result_text, self._conversation, retry_files = self._executor.execute_step(
                    f"Retry: {step} (previous attempt failed: {eval_result.reason})",
                    self._conversation,
                )
                self._last_generated_files.extend(retry_files)

            step_results.append(result_text)
            self._trim_conversation()

        # 6. Synthesis
        if len(steps) > 1:
            final = self._synthesize(safe_input, step_results)
        else:
            final = step_results[0] if step_results else "I wasn't able to complete the task."

        # 7. INTEGRITY CHECK — catch the LLM lying about scheduling
        # If the response claims a meeting was scheduled but no .ics was actually created,
        # strip the false claim and ask for a time instead.
        has_ics = any(gf.get("type") == "ics" for gf in self._last_generated_files)
        scheduling_requested = any(
            w in user_input.lower()
            for w in ["schedule", "meeting", "calendar", "event", "remind"]
        )

        if scheduling_requested and not has_ics and not time_confirmed:
            # The LLM probably claimed it created an event — strip that claim
            # and append a proper scheduling prompt
            schedule_claims = [
                "has been added to your calendar",
                "has been scheduled",
                "event has been created",
                "meeting has been created",
                "added to calendar",
                "scheduled for",
                "created a calendar event",
                "event created",
            ]
            for claim in schedule_claims:
                if claim.lower() in final.lower():
                    # Find and remove the sentence containing the claim
                    sentences = final.split(". ")
                    cleaned = [s for s in sentences if claim.lower() not in s.lower()]
                    final = ". ".join(cleaned)
                    logger.warning("Stripped false scheduling claim from response")

            # Get free times to suggest
            events_tool = self._registry.get("list_events")
            free_times = ""
            if events_tool:
                result = events_tool.run()
                if result.success:
                    lines = result.data.split("\n")
                    free_lines = [l.strip() for l in lines if l.strip().startswith("FREE:")]
                    if free_lines:
                        free_times = "\n".join(f"  • {l.replace('FREE: ', '')}" for l in free_lines[:5])

            # Append scheduling question
            if free_times:
                final = final.rstrip(". \n") + (
                    "\n\nTo schedule the meeting, when works best for you? "
                    "Based on your calendar, these times are free:\n"
                    f"{free_times}\n\n"
                    "Just reply with your preferred date and time."
                )
            else:
                final = final.rstrip(". \n") + (
                    "\n\nTo schedule the meeting, what date and time work for you?"
                )

        # 8. Restore ALL PII from the cumulative session map
        if self._session_entity_map:
            final = restore(final, self._session_entity_map)
            for gf in self._last_generated_files:
                for key in ("label", "to", "subject", "body"):
                    if key in gf and isinstance(gf[key], str):
                        gf[key] = restore(gf[key], self._session_entity_map)

        # 9. Deduplicate generated files — keep only the LAST file per type
        seen_types: dict[str, dict] = {}
        for gf in self._last_generated_files:
            ftype = gf.get("type", "unknown")
            seen_types[ftype] = gf
        self._last_generated_files = list(seen_types.values())

        # 10. Persist
        self._db.add_message(self._session_id, "assistant", final)
        self._db.update_task(task_id, "done", result=final[:500])
        logger.info("Agent response: %s", final[:120])
        return final

    # ---- Helpers --------------------------------------------------------- #

    def _process_attachments(self, file_paths: list[str]) -> str:
        from tools.document_adapter import _extract_text
        parts: list[str] = []
        for fp in file_paths:
            p = Path(fp)
            if not p.exists():
                parts.append(f"[File not found: {p.name}]")
                continue
            try:
                text = _extract_text(p)
                if len(text) > 4000:
                    text = text[:4000] + "\n[...truncated]"
                parts.append(f"--- {p.name} ---\n{text}")
            except Exception as exc:
                parts.append(f"[Could not read {p.name}: {exc}]")
        return "\n\n".join(parts)

    def _build_context(self, user_input: str) -> str:
        parts: list[str] = []
        recent = self._db.recent_tasks(self._session_id, limit=3)
        if recent:
            parts.append("Recent tasks:")
            for t in recent:
                parts.append(f"  - [{t['status']}] {t['goal']}")
        memories = self._faiss.search(user_input, top_k=3)
        if memories:
            parts.append("Relevant memories:")
            for m in memories:
                parts.append(f"  - {m.get('text', '')[:200]} (source: {m.get('source', 'unknown')})")
        return "\n".join(parts) if parts else "(no prior context)"

    def _synthesize(self, user_input: str, step_results: list[str]) -> str:
        combined = "\n---\n".join(
            f"Step result {i+1}:\n{r}" for i, r in enumerate(step_results)
        )
        prompt = (
            f"The user asked: {user_input}\n\n"
            f"Here are the results from each step of the plan:\n{combined}\n\n"
            "Synthesize these into a clear, helpful response.\n"
            "CRITICAL RULES:\n"
            "- If an email was drafted, show the EXACT body text from the draft_reply tool result. "
            "Do NOT rewrite, expand, or shorten it. Copy it verbatim.\n"
            "- If a calendar event was created, state the date, time, and title.\n"
            "- Do NOT use HTML tags. Do NOT add meta-commentary.\n"
            "- Do NOT start with 'Here is the synthesized response' or similar preamble."
        )
        try:
            resp = self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.3},
            )
            return resp["message"]["content"]
        except Exception as exc:
            logger.error("Synthesis failed: %s", exc)
            return combined

    def _trim_conversation(self):
        if len(self._conversation) > self._buffer_size:
            self._conversation = self._conversation[-self._buffer_size:]
