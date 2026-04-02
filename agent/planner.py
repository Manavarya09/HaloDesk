"""Planner — uses the LLM to decompose a user goal into a list of tool-based steps."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.prompts import PLAN_PROMPT

logger = logging.getLogger(__name__)


class Planner:
    """Ask the LLM to produce a step-by-step plan for the user's request."""

    def __init__(self, ollama_client, model: str, max_steps: int = 10):
        self._client = ollama_client
        self._model = model
        self._max_steps = max_steps

    def plan(self, user_input: str, context: str = "") -> list[str]:
        """Return an ordered list of step descriptions."""
        prompt = PLAN_PROMPT.format(user_input=user_input, context=context or "(none)")

        try:
            resp = self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.3},
            )
            raw = resp["message"]["content"].strip()
            # Try to extract JSON array from the response
            steps = self._parse_steps(raw)
            if not steps:
                # Fallback: single step
                steps = [user_input]
            return steps[: self._max_steps]
        except Exception as exc:
            logger.error("Planning failed: %s", exc)
            # Graceful fallback — treat the whole request as one step
            return [user_input]

    @staticmethod
    def _parse_steps(raw: str) -> list[str]:
        """Extract a JSON array of strings from the LLM output, tolerating markdown fences."""
        text = raw.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
        # Find first [ and last ]
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            arr = json.loads(text[start : end + 1])
            if isinstance(arr, list) and all(isinstance(s, str) for s in arr):
                return arr
        except json.JSONDecodeError:
            pass
        return []
