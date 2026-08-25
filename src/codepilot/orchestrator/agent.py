"""The Orchestrator: root deep agent (Component 1).

Phase 1 scope: build the orchestrator and have it turn one classified issue
into a todo checklist. Subagent spawning (Repo Explorer / Coder / Test / PR
agents) is wired in starting Phase 3 - `build_orchestrator` gains a
`subagents=` list then; it deliberately takes none yet.
"""
from __future__ import annotations

from dataclasses import dataclass

from deepagents import FilesystemPermission, create_deep_agent
from langchain_core.language_models import BaseChatModel

from src.codepilot.config import settings
from src.codepilot.llm import build_llm
from src.codepilot.memory.working import WorkingMemory
from src.codepilot.orchestrator.classifier import IssueClassification, classify_issue
from src.codepilot.orchestrator.issue import Issue
from src.codepilot.orchestrator.state_machine import TaskState, TaskStateMachine

_WORKFLOW_HINTS = {
    "bug_fix": "reproduce -> localize -> fix -> verify",
    "feature_addition": "explore_pattern -> design -> implement -> test -> document",
    "dependency_update": "check_changelog -> update -> resolve_conflicts -> test_all",
    "documentation": "read_existing -> draft -> review_accuracy -> update_index",
    "config_change": "identify_setting -> change -> validate -> test",
}

_TRIAGE_PROMPT = """You have been told this issue's category: {task_type}.

Your job right now is ONLY to plan, not to implement:
1. Read the issue title and body below.
2. You MUST call the `write_todos` tool exactly once with an implementation
   checklist appropriate for a `{task_type}` task, following this workflow
   shape: {workflow_hint}
   This is a hard requirement, not a suggestion - do not skip it just
   because the task looks simple, and do not merely describe the plan in
   your text response instead of calling the tool.
   Use `write_todos` specifically for this, and nothing else: do NOT call
   `write_file`, `edit_file`, or any other tool to record the plan (e.g. do
   not write a plan to a markdown file) - `write_todos` is the only
   correct way to record it.
3. Only after calling `write_todos`, reply with a one-paragraph summary of
   your plan.

Do not try to read or edit any files - the Repo Explorer and Coder agents
handle that in later stages. You are producing a plan only, and the plan
itself must be recorded via `write_todos`, not written to a file.

Issue title: {title}

Issue body:
{body}
"""

_ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the Orchestrator of CodePilot, a multi-agent autonomous coding "
    "platform. You triage GitHub issues, plan them with write_todos, and "
    "(in later stages) delegate implementation to subagents via the task "
    "tool. When only asked to plan, do not attempt implementation."
)


@dataclass
class TriageResult:
    issue: Issue
    classification: IssueClassification
    todos: list[dict[str, str]]
    plan_summary: str
    state_machine: TaskStateMachine
    working_memory: WorkingMemory


def build_orchestrator(llm: BaseChatModel | None = None):
    """Compile the root Orchestrator deep agent.

    Two things found by actually running this against a real (non-Claude)
    model, gpt-4o, that unit tests with fake agents never exercised:

    1. `write_todos` isn't necessarily registered at all - which harness
       profile `create_deep_agent` selects (and therefore whether
       `TodoListMiddleware` is included) depends on the model provider.
       Explicitly adding it below guarantees the tool the prompt requires
       actually exists to call.
    2. Without `write_todos` available, gpt-4o used `write_file` as a
       substitute way to "record a plan" (e.g. writing
       `implementation_plan.md`) - and kept retrying that under different
       filenames even after being told not to. Denying write access
       entirely closes that off structurally; relying on the prompt alone
       was not enough.
    """
    from langchain.agents.middleware import TodoListMiddleware

    model = llm or build_llm()
    return create_deep_agent(
        model=model,
        system_prompt=_ORCHESTRATOR_SYSTEM_PROMPT,
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        middleware=[TodoListMiddleware()],
    )


def run_triage(issue: Issue, *, llm: BaseChatModel | None = None, agent=None) -> TriageResult:
    """Classify an issue and produce an implementation checklist for it.

    No GitHub call is made here - `issue` can be a hardcoded fixture (Phase 1
    check) or a real issue fetched by the poller (Phase 2 onward).
    """
    model = llm or build_llm()

    classification = classify_issue(model, title=issue.title, body=issue.body)

    working_memory = WorkingMemory(issue_id=issue.id, issue_title=issue.title, issue_body=issue.body)
    working_memory.record_classification(classification.task_type.value)

    state_machine = TaskStateMachine(issue_id=issue.id)

    orchestrator = agent or build_orchestrator(model)
    prompt = _TRIAGE_PROMPT.format(
        task_type=classification.task_type.value,
        workflow_hint=_WORKFLOW_HINTS[classification.task_type.value],
        title=issue.title,
        body=issue.body,
    )
    result_state = orchestrator.invoke({"messages": [{"role": "user", "content": prompt}]})

    todos = result_state.get("todos", [])
    final_message = result_state["messages"][-1]
    plan_summary = getattr(final_message, "content", str(final_message))

    # Planning done; next stop is the Repo Explorer (Phase 3).
    state_machine.transition(TaskState.EXPLORING, reason="triage complete, todos written")

    return TriageResult(
        issue=issue,
        classification=classification,
        todos=todos,
        plan_summary=plan_summary,
        state_machine=state_machine,
        working_memory=working_memory,
    )
