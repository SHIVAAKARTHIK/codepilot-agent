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
from src.codepilot.memory.semantic import Lesson, SemanticMemory, lessons_to_prompt_block
from src.codepilot.memory.working import WorkingMemory
from src.codepilot.skills.skill import Skill
from src.codepilot.test_agent import agent as test_agent
from src.codepilot.test_agent.runner import TestResult, run_test_suite

_CODER_SYSTEM_PROMPT = (
    "You are the Coder agent of CodePilot. You work ONLY inside your "
    "sandbox - a copy of just the files relevant to this task, not the "
    "full repository. Follow this loop:\n"
    "1. Use read_file to read the relevant files.\n"
    "2. Call write_todos once with your implementation plan.\n"
    "3. Make surgical edits with edit_file (prefer targeted edits over "
    "full-file rewrites).\n"
    "4. Use execute to run/verify the code still works.\n"
    "5. Spawn the test_agent subagent (via the task tool) so it can add or "
    "update test coverage for your change, then reply with a short summary "
    "of what you changed and why.\n"
    "Some operations are blocked by guardrails (dangerous shell commands; "
    "edits to secret/credential files). If a tool call comes back blocked, "
    "do not retry it - explain what you wanted to do and move on."
)

_CODER_TASK_PROMPT = """Task type: {task_type}
Issue: {issue_title}

Relevant files in your sandbox:
{relevant_files}

{skill_block}
{lessons_block}
Implement a fix/change for this issue, following the loop in your system prompt."""

_RETRY_PROMPT = """The test suite failed after your last change (attempt {attempt} of {max_retries}).

Failure summary:
{failure_summary}

Fix the failure(s) above. Make a surgical edit, then verify with execute again."""

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
    test_result: TestResult | None = None
    retries: int = 0
    changed_files: list[str] = field(default_factory=list)
    lessons_used: list[Lesson] = field(default_factory=list)


def build_llm() -> ChatAnthropic:
    settings.validate_for_llm()
    return ChatAnthropic(model=settings.model_name, api_key=settings.anthropic_api_key)


def build_coder(
    sandbox_dir: Path,
    *,
    llm: ChatAnthropic | None = None,
    on_violation=None,
    subagents: list[dict] | None = None,
):
    """Compile the Coder subagent, wired to its own sandboxed backend,
    guardrail middleware, forbidden-filename permissions, and (optionally)
    the Test Agent as a spawnable subagent."""
    model = llm or build_llm()
    backend = LocalShellBackend(root_dir=str(sandbox_dir), virtual_mode=True)
    guardrail = GuardrailMiddleware(sandbox_root=sandbox_dir, on_violation=on_violation)
    return create_deep_agent(
        model=model,
        backend=backend,
        permissions=build_coder_permissions(),
        middleware=[guardrail],
        subagents=subagents,
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
    skill: Skill | None = None,
    llm: ChatAnthropic | None = None,
    agent=None,
    max_retries: int | None = None,
    semantic_memory: SemanticMemory | None = None,
    repo_id: str | None = None,
) -> CoderResult:
    """Drives the full inner loop: retrieve past lessons -> read -> plan ->
    edit -> verify -> spawn Test Agent -> (retry up to `max_retries` on
    failure) -> diff preview.

    Pass/fail for the retry loop comes from `run_test_suite()`
    (deterministic), not the Coder's own self-report.

    If `semantic_memory` is given, the top-3 most similar past lessons for
    this `repo_id` + task type are retrieved and injected into the Coder's
    prompt before it starts (Component 5).
    """
    max_retries = settings.max_coder_retries if max_retries is None else max_retries
    repo_id = repo_id or str(Path(repo_root).resolve())

    sandbox_dir = create_sandbox(
        Path(repo_root),
        working_memory.relevant_files,
        sandbox_base=settings.sandbox_root,
        issue_id=working_memory.issue_id,
    )
    before = _snapshot(sandbox_dir)

    violations: list[GuardrailViolation] = []
    coder = agent
    if coder is None:
        test_subagent = test_agent.as_subagent(sandbox_dir, llm=llm, on_violation=violations.append)
        coder = build_coder(sandbox_dir, llm=llm, on_violation=violations.append, subagents=[test_subagent])

    lessons: list[Lesson] = []
    if semantic_memory is not None and working_memory.task_type:
        lessons = semantic_memory.retrieve_similar_lessons(
            repo=repo_id,
            task_type=working_memory.task_type,
            query=f"{working_memory.issue_title}\n{working_memory.issue_body}",
        )

    skill_block = f"{skill.to_prompt_block()}\n" if skill else ""
    lessons_block = lessons_to_prompt_block(lessons)
    prompt = _CODER_TASK_PROMPT.format(
        task_type=working_memory.task_type or "unknown",
        issue_title=working_memory.issue_title,
        relevant_files="\n".join(f"- {f}" for f in working_memory.relevant_files) or "(none listed)",
        skill_block=skill_block,
        lessons_block=lessons_block,
    )

    final_message = ""
    todos: list[dict] = []
    test_result: TestResult | None = None
    attempt = 0

    while True:
        result_state = coder.invoke({"messages": [{"role": "user", "content": prompt}]})
        final_message = getattr(result_state["messages"][-1], "content", "")
        todos = result_state.get("todos", [])

        test_result = run_test_suite(sandbox_dir)
        working_memory.record_test_result(
            passed=test_result.passed,
            details={"no_tests_collected": test_result.no_tests_collected, "counts": test_result.counts},
        )

        if test_result.passed or test_result.no_tests_collected:
            break
        if attempt >= max_retries:
            break

        attempt += 1
        working_memory.increment_retry()
        prompt = _RETRY_PROMPT.format(
            attempt=attempt,
            max_retries=max_retries,
            failure_summary="\n".join(test_result.failure_summary) or test_result.raw_output[-2000:],
        )

    after = _snapshot(sandbox_dir)
    diff_text = generate_unified_diff(before, after) or "(no changes)\n"
    changed_files = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))

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
        test_result=test_result,
        retries=attempt,
        changed_files=changed_files,
        lessons_used=lessons,
    )
