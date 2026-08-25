"""Test Agent: the subagent spawned by the Coder for verification (per the
Component 3/Agent Responsibilities table).

Its LLM role is deliberately narrow: given what the Coder changed, write or
update whatever test(s) are needed to cover it (e.g. a reproduction test
for a bug fix) via `write_file`. The actual pass/fail signal that drives
the Coder's retry loop comes from `runner.run_test_suite()` - deterministic
pytest execution + parsing - not this subagent's self-report.

Built as a real `CompiledSubAgent` so the Coder spawns it through
deepagents' own `task` tool, not a Python function call - this is the one
place in the pipeline that uses genuine nested subagent spawning (see
BUILD_PLAN.md for why Orchestrator->Coder and Coder->PR-Agent stay as
explicit Python-orchestrated stages instead).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_anthropic import ChatAnthropic

from src.codepilot.coder.middleware import GuardrailMiddleware
from src.codepilot.coder.permissions import build_coder_permissions
from src.codepilot.config import settings

_TEST_AGENT_SYSTEM_PROMPT = (
    "You are the Test Agent, spawned by the Coder to verify its changes. "
    "You work inside the same sandbox as the Coder. Your job:\n"
    "1. Read the files the Coder changed.\n"
    "2. If there is no test covering this change yet, write one with "
    "write_file - a reproduction test for a bug fix, or a basic test for "
    "a new feature - following the existing test file conventions in the "
    "sandbox if any exist.\n"
    "3. Reply with a short summary of what test(s) you added or found.\n"
    "Do not attempt to fix the underlying code yourself - that is the "
    "Coder's job. Do not run the full suite yourself; the harness runs it "
    "after you finish."
)


def build_llm() -> ChatAnthropic:
    settings.validate_for_llm()
    return ChatAnthropic(model=settings.model_name, api_key=settings.anthropic_api_key)


def build_test_agent(sandbox_dir: Path, *, llm: ChatAnthropic | None = None, on_violation=None):
    model = llm or build_llm()
    backend = LocalShellBackend(root_dir=str(sandbox_dir), virtual_mode=True)
    guardrail = GuardrailMiddleware(sandbox_root=sandbox_dir, on_violation=on_violation)
    return create_deep_agent(
        model=model,
        backend=backend,
        permissions=build_coder_permissions(),
        middleware=[guardrail],
        system_prompt=_TEST_AGENT_SYSTEM_PROMPT,
    )


def as_subagent(sandbox_dir: Path, *, llm: ChatAnthropic | None = None, on_violation=None) -> dict[str, Any]:
    """A `CompiledSubAgent` spec the Coder can spawn via its `task` tool."""
    return {
        "name": "test_agent",
        "description": (
            "Writes or updates test file(s) to cover the current change "
            "(e.g. a reproduction test for a bug fix). Spawn this before "
            "you consider your work done."
        ),
        "runnable": build_test_agent(sandbox_dir, llm=llm, on_violation=on_violation),
    }
