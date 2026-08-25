"""The Coder Agent: implements a fix inside a sandboxed copy of only the
relevant repo files (Component 3).

Inner loop (per spec): read relevant files -> plan via write_todos -> edit
surgically -> verify via execute -> (Test Agent + retry loop land in
Phase 5) -> diff preview written before finalizing.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_anthropic import ChatAnthropic

from src.codepilot.coder.guardrails import GuardrailViolation
from src.codepilot.coder.middleware import GuardrailMiddleware
from src.codepilot.coder.permissions import build_coder_permissions
from src.codepilot.coder.sandbox import create_sandbox
from src.codepilot.config import settings
from src.codepilot.memory.working import WorkingMemory

_CODER_SYSTEM_PROMPT = (
    "You are the Coder agent of CodePilot. You work ONLY inside your "
    "sandbox - a copy of just the files relevant to this task, not the "
    "full repository. Follow this loop:\n"
    "1. Use read_file to read the relevant files.\n"
    "2. Call write_todos once with your implementation plan.\n"
    "3. Make surgical edits with edit_file (prefer targeted edits over "
    "full-file rewrites).\n"
    "4. Use execute to run/verify the code still works.\n"
    "5. Reply with a short summary of what you changed and why.\n"
    "Some operations are blocked by guardrails (dangerous shell commands; "
    "edits to secret/credential files). If a tool call comes back blocked, "
    "do not retry it - explain what you wanted to do and move on."
)

_CODER_TASK_PROMPT = """Task type: {task_type}
Issue: {issue_title}

Relevant files in your sandbox:
{relevant_files}

Implement a fix/change for this issue, following the loop in your system prompt."""

# Files/dirs never included in before/after snapshots - the diff artifact
# itself, and its containing folder, shouldn't diff against themselves.
_SNAPSHOT_EXCLUDE_PREFIX = "working/"


@dataclass
class CoderResult:
    sandbox_dir: Path
    diff_text: str
    violations: list[GuardrailViolation] = field(default_factory=list)
    final_message: str = ""
    todos: list[dict] = field(default_factory=list)


def build_llm() -> ChatAnthropic:
    settings.validate_for_llm()
    return ChatAnthropic(model=settings.model_name, api_key=settings.anthropic_api_key)


def build_coder(sandbox_dir: Path, *, llm: ChatAnthropic | None = None, on_violation=None):
    """Compile the Coder subagent, wired to its own sandboxed backend,
    guardrail middleware, and forbidden-filename permissions."""
    model = llm or build_llm()
    backend = LocalShellBackend(root_dir=str(sandbox_dir), virtual_mode=True)
    guardrail = GuardrailMiddleware(sandbox_root=sandbox_dir, on_violation=on_violation)
    return create_deep_agent(
        model=model,
        backend=backend,
        permissions=build_coder_permissions(),
        middleware=[guardrail],
        system_prompt=_CODER_SYSTEM_PROMPT,
    )


def _snapshot(sandbox_dir: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sandbox_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(sandbox_dir).as_posix()
        if rel.startswith(_SNAPSHOT_EXCLUDE_PREFIX):
            continue
        try:
            snapshot[rel] = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return snapshot


def generate_unified_diff(before: dict[str, str], after: dict[str, str]) -> str:
    """Deterministic, code-computed diff rather than LLM-authored text -
    more reliable than asking the model to hand-write a correct unified
    diff, and trivially verifiable."""
    parts = []
    for path in sorted(set(before) | set(after)):
        b, a = before.get(path, ""), after.get(path, "")
        if a == b:
            continue
        diff = difflib.unified_diff(
            b.splitlines(keepends=True), a.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}",
        )
        parts.append("".join(diff))
    return "\n".join(parts)


def run_coder_task(
    *,
    repo_root: Path,
    working_memory: WorkingMemory,
    llm: ChatAnthropic | None = None,
    agent=None,
) -> CoderResult:
    sandbox_dir = create_sandbox(
        Path(repo_root),
        working_memory.relevant_files,
        sandbox_base=settings.sandbox_root,
        issue_id=working_memory.issue_id,
    )
    before = _snapshot(sandbox_dir)

    violations: list[GuardrailViolation] = []
    coder = agent or build_coder(sandbox_dir, llm=llm, on_violation=violations.append)

    prompt = _CODER_TASK_PROMPT.format(
        task_type=working_memory.task_type or "unknown",
        issue_title=working_memory.issue_title,
        relevant_files="\n".join(f"- {f}" for f in working_memory.relevant_files) or "(none listed)",
    )
    result_state = coder.invoke({"messages": [{"role": "user", "content": prompt}]})
    final_message = getattr(result_state["messages"][-1], "content", "")
    todos = result_state.get("todos", [])

    after = _snapshot(sandbox_dir)
    diff_text = generate_unified_diff(before, after) or "(no changes)\n"

    working_dir = sandbox_dir / "working"
    working_dir.mkdir(exist_ok=True)
    (working_dir / "proposed_diff.txt").write_text(diff_text, encoding="utf-8")

    working_memory.current_diff = diff_text

    return CoderResult(
        sandbox_dir=sandbox_dir,
        diff_text=diff_text,
        violations=violations,
        final_message=final_message,
        todos=todos,
    )
