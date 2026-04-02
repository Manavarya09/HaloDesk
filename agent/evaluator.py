"""Evaluator — checks whether each step succeeded and decides on retry/recovery."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from agent.prompts import EVALUATE_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    success: bool
    reason: str
    should_retry: bool


class Evaluator:
    """Ask the LLM (or use heuristics) to evaluate a step's outcome."""

    def __init__(self, ollama_client, model: str, max_retries: int = 2):
        self._client = ollama_client
        self._model = model
        self._max_retries = max_retries

    def evaluate(self, step: str, tool_name: str, tool_result: str) -> EvalResult:
        """Evaluate whether a step succeeded."""
        # Fast-path heuristic: if the result contains [ERROR], it failed
        if "[ERROR]" in tool_result or tool_result.startswith("[LLM error"):
            return EvalResult(success=False, reason=tool_result, should_retry=True)

        # For short, clear results — assume success
        if len(tool_result) < 500 and "[ERROR]" not in tool_result:
            return EvalResult(success=True, reason="Tool returned a result.", should_retry=False)

        # Use LLM for ambiguous cases
        try:
            prompt = EVALUATE_PROMPT.format(
                step=step, tool_name=tool_name, tool_result=tool_result[:2000]
            )
            resp = self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1},
            )
            raw = resp["message"]["content"].strip()
            return self._parse_eval(raw)
        except Exception as exc:
            logger.warning("Evaluation LLM call failed: %s — assuming success", exc)
            return EvalResult(success=True, reason="Eval skipped (LLM error).", should_retry=False)

    @staticmethod
    def _parse_eval(raw: str) -> EvalResult:
        text = raw.strip()
        # Strip fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                obj = json.loads(text[start : end + 1])
                return EvalResult(
                    success=bool(obj.get("success", True)),
                    reason=obj.get("reason", ""),
                    should_retry=bool(obj.get("should_retry", False)),
                )
            except json.JSONDecodeError:
                pass
        # Fallback
        return EvalResult(success=True, reason=raw[:200], should_retry=False)

    @property
    def max_retries(self) -> int:
        return self._max_retries
