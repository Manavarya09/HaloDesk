"""Executor — runs individual plan steps by using LLM tool-calling to select and invoke tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.prompts import SYSTEM_PROMPT
from tools import ToolRegistry, ToolResult
from tools.privacy import restore

logger = logging.getLogger(__name__)

# Tools that write files — their string arguments should have PII restored
# so that generated .eml and .ics files contain real names, not placeholders.
_WRITE_TOOLS = {"draft_reply", "create_event", "create_reminder"}

class Executor:
    """Given a plan step + conversation context, use the LLM to pick and call tools."""

    def __init__(self, ollama_client, model: str, registry: ToolRegistry):
        self._client = ollama_client
        self._model = model
        self._registry = registry
        self._entity_map: dict[str, str] = {}
        self._time_confirmed: bool = False  # Gate: blocks create_event until user confirms time

    def set_entity_map(self, entity_map: dict[str, str]):
        self._entity_map = entity_map

    def set_time_confirmed(self, confirmed: bool):
        """Set whether the user has provided a specific date/time in their message."""
        self._time_confirmed = confirmed

    def execute_step(
        self,
        step: str,
        conversation: list[dict],
        max_tool_rounds: int = 5,
    ) -> tuple[str, list[dict], list[dict]]:
        """
        Execute a single plan step.

        Returns (final_text_response, updated_conversation, generated_files).
        """
        messages = list(conversation)
        messages.append({"role": "user", "content": f"Execute this step: {step}"})

        tool_defs = self._registry.ollama_tool_definitions()
        collected_files: list[dict] = []

        for round_num in range(max_tool_rounds):
            try:
                resp = self._client.chat(
                    model=self._model,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                    tools=tool_defs,
                    options={"temperature": 0.2},
                )
            except Exception as exc:
                logger.error("LLM call failed (round %d): %s", round_num, exc)
                error_msg = f"[LLM error: {exc}]"
                messages.append({"role": "assistant", "content": error_msg})
                return error_msg, messages, collected_files

            msg = resp["message"]

            # If the model returned tool calls, execute them
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                messages.append(msg)  # assistant message with tool_calls
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = tc["function"].get("arguments", {})

                    # Restore PII in arguments for write-tools
                    if fn_name in _WRITE_TOOLS and self._entity_map:
                        fn_args = self._restore_args(fn_args)

                    # SCHEDULING GATE: Block create_event/create_reminder if
                    # user hasn't provided a specific time in their message.
                    if fn_name in ("create_event", "create_reminder") and not self._time_confirmed:
                        result = ToolResult(
                            success=False,
                            error=(
                                "BLOCKED: Cannot create event — the user has not provided a specific date and time. "
                                "You MUST ask the user when they want to schedule. "
                                "Use list_events to check their calendar, then suggest FREE time slots and ask them to pick one."
                            ),
                        )
                        logger.warning("Scheduling gate blocked %s — no time confirmed", fn_name)
                    else:
                        result = self._call_tool(fn_name, fn_args)
                    logger.info("Tool %s → %s", fn_name, "OK" if result.success else result.error)
                    # Collect any generated files
                    if result.generated_files:
                        collected_files.extend(result.generated_files)
                    messages.append({
                        "role": "tool",
                        "content": str(result),
                    })
                continue  # let the LLM process tool results

            # No tool calls — LLM produced a final text response
            text = msg.get("content", "")
            messages.append({"role": "assistant", "content": text})
            return text, messages, collected_files

        # Exhausted rounds
        final = "[Executor] Reached max tool rounds without a final answer."
        messages.append({"role": "assistant", "content": final})
        return final, messages, collected_files

    def _restore_args(self, args: dict) -> dict:
        """Replace PII placeholders in all string values of the args dict."""
        restored = {}
        for key, val in args.items():
            if isinstance(val, str):
                restored[key] = restore(val, self._entity_map)
            else:
                restored[key] = val
        return restored

    def _call_tool(self, name: str, args: dict) -> ToolResult:
        tool = self._registry.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")
        try:
            return tool.run(**args)
        except Exception as exc:
            logger.error("Tool %s raised: %s", name, exc)
            return ToolResult(success=False, error=str(exc))
