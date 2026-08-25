"""GuardrailMiddleware: blocks dangerous `execute` commands and forbidden
file edits at the tool-call layer, before they ever reach the backend.

Necessary because `LocalShellBackend`'s own docs are explicit that path
permissions provide **no** protection once shell execution is enabled -
"virtual_mode=True and path-based restrictions provide NO security with
shell access enabled, since commands can access any path on the system."
deepagents' own recommendation for this backend is exactly what this
middleware implements: intercept every risky tool call before it runs,
rather than trusting the backend to sandbox `execute` itself.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from src.codepilot.coder.guardrails import GuardrailViolation, check_execute_command, check_file_edit


class GuardrailMiddleware(AgentMiddleware):
    """Wraps `execute` / `write_file` / `edit_file` tool calls. On a match,
    the tool is never invoked - the model gets back an explanatory error
    message instead of a result, and `on_violation` (if given) is notified
    so the caller can surface it as a human-approval event."""

    name = "codepilot_guardrails"

    def __init__(
        self,
        *,
        sandbox_root: str | Path,
        on_violation: Callable[[GuardrailViolation], None] | None = None,
    ) -> None:
        super().__init__()
        self.sandbox_root = sandbox_root
        self.on_violation = on_violation

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        tool_name = request.tool_call.get("name")
        args = request.tool_call.get("args") or {}

        violation: GuardrailViolation | None = None
        if tool_name == "execute":
            violation = check_execute_command(args.get("command", ""), sandbox_root=self.sandbox_root)
        elif tool_name in ("write_file", "edit_file"):
            violation = check_file_edit(args.get("file_path", ""))

        if violation is None:
            return handler(request)

        if self.on_violation:
            self.on_violation(violation)

        return ToolMessage(
            content=(
                f"BLOCKED by CodePilot guardrails ({violation.kind}): {violation.reason}\n"
                f"Attempted: {tool_name}({args})\n"
                "This operation requires human approval and was NOT performed. "
                "Explain to the user what you intended to do and why, and do not retry it."
            ),
            tool_call_id=request.tool_call.get("id", ""),
            status="error",
        )
