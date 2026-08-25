"""The Orchestrator: root deep agent (Component 1).

Phase 1 scope: build the orchestrator and have it turn one classified issue
into a todo checklist. Subagent spawning (Repo Explorer / Coder / Test / PR
agents) is wired in starting Phase 3 - `build_orchestrator` gains a
`subagents=` list then; it deliberately takes none yet.
"""
from __future__ import annotations

from dataclasses import dataclass

from deepagents import create_deep_agent
from langchain_anthropic import ChatAnthropic

from src.codepilot.config import settings
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
2. Call the `write_todos` tool exactly once with an implementation checklist
   appropriate for a `{task_type}` task, following this workflow shape:
   {workflow_hint}
3. After calling `write_todos`, reply with a one-paragraph summary of your plan.

Do not try to read or edit any files - the Repo Explorer and Coder agents
handle that in later stages. You are producing a plan only.

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


def build_llm() -> ChatAnthropic:
    settings.validate_for_llm()
    return ChatAnthropic(model=settings.model_name, api_key=settings.anthropic_api_key)


def build_orchestrator(llm: ChatAnthropic | None = None):
    """Compile the root Orchestrator deep agent."""
    model = llm or build_llm()
    return create_deep_agent(model=model, system_prompt=_ORCHESTRATOR_SYSTEM_PROMPT)


def run_triage(issue: Issue, *, llm: ChatAnthropic | None = None, agent=None) -> TriageResult:
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
