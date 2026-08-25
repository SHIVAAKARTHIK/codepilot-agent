"""TUI tests. The pipeline itself is faked (it's already thoroughly tested
in tests/test_pipeline.py) - what's being proven here is the TUI's own
wiring: panels mount and render, issues discovered by the poll worker
reach the Issues panel, and the Human Approval flow genuinely blocks a
background worker thread until a real keypress resolves it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.codepilot.orchestrator.issue import Issue
from src.codepilot.orchestrator.state_machine import TaskState, TaskStateMachine
from src.codepilot.pr_agent.gates import PendingApproval
from src.codepilot.tui.app import CodePilotApp
from src.codepilot.tui.demo_source import StaticIssueSource
from src.codepilot.tui.panels.active_task import ActiveTaskPanel
from src.codepilot.tui.panels.agent_logs import AgentLogsPanel
from src.codepilot.tui.panels.human_approval import HumanApprovalPanel
from src.codepilot.tui.panels.issues import IssuesPanel

pytestmark = pytest.mark.anyio


def _make_app(issue_source=None, **overrides) -> CodePilotApp:
    kwargs = {
        "repo_root": None,
        "repo_explorer": None,
        "episodic_memory": None,
        "semantic_memory": None,
        "github_client": None,
        "repo_id": "test/repo",
        "issue_source": issue_source or StaticIssueSource([]),
        "poll_interval_minutes": 60,
    }
    kwargs.update(overrides)
    return CodePilotApp(**kwargs)


async def _wait_until(predicate, *, timeout_steps=60, pilot=None) -> bool:
    for _ in range(timeout_steps):
        await pilot.pause(0.05)
        if predicate():
            return True
    return False


async def test_app_mounts_with_all_four_panels():
    app = _make_app()
    async with app.run_test() as pilot:
        assert app.query_one("#issues", IssuesPanel) is not None
        assert app.query_one("#active-task", ActiveTaskPanel) is not None
        assert app.query_one("#agent-logs", AgentLogsPanel) is not None
        assert app.query_one("#human-approval", HumanApprovalPanel) is not None


async def test_skip_issue_on_empty_queue_does_not_crash():
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause()
        # no exception is the assertion here; app is still running
        assert app.is_running


async def test_new_task_modal_opens_and_cancels():
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.press("i")
        await pilot.pause()
        assert len(app.screen_stack) == 2  # modal pushed

        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1  # modal dismissed


async def test_queued_issue_reaches_issues_panel(monkeypatch):
    """The poll worker (a real background thread) discovers an issue and
    the Issues panel updates via call_from_thread - exercises the actual
    cross-thread UI update path, not just direct method calls."""

    def fake_pipeline(issue, **kwargs):
        sm = TaskStateMachine(issue_id=issue.id, state=TaskState.DONE)
        return SimpleNamespace(
            issue=issue, state_machine=sm, triage=None, coder_result=None,
            pr_result=SimpleNamespace(status="PR_OPENED", pr_url="https://example.com/pr/1"), error=None,
        )

    monkeypatch.setattr("src.codepilot.tui.app.run_full_pipeline_for_issue", fake_pipeline)

    issue = Issue(id="queue-test-1", number=1, title="Fix the thing", body="...")
    app = _make_app(issue_source=StaticIssueSource([issue]))

    async with app.run_test() as pilot:
        table = app.query_one("#issues", IssuesPanel)
        found = await _wait_until(lambda: "queue-test-1" in table._known, pilot=pilot)
        assert found, "issue never reached the Issues panel"


async def test_approval_flow_resolves_via_keyboard(monkeypatch):
    """The core Phase 8 'done when' proof: a pending approval genuinely
    blocks the task-processor worker thread until a real keypress resolves
    it, and the resolution actually reaches the pipeline's decision."""
    decisions = []

    def fake_pipeline(issue, **kwargs):
        on_approval_needed = kwargs["on_approval_needed"]
        pending = [PendingApproval(gate="pr_target", reason="test reason", detail="base: main")]
        decision = on_approval_needed(pending)
        decisions.append(decision)
        state = TaskState.DONE if decision.approved else TaskState.FAILED
        sm = TaskStateMachine(issue_id=issue.id, state=state)
        return SimpleNamespace(
            issue=issue,
            state_machine=sm,
            triage=None,
            coder_result=None,
            pr_result=SimpleNamespace(status="PR_OPENED", pr_url="https://example.com/pr/2") if decision.approved else None,
            error=None if decision.approved else "Rejected by human",
        )

    monkeypatch.setattr("src.codepilot.tui.app.run_full_pipeline_for_issue", fake_pipeline)

    issue = Issue(id="approval-test-1", number=2, title="Needs approval", body="...")
    app = _make_app(issue_source=StaticIssueSource([issue]))

    async with app.run_test() as pilot:
        reached = await _wait_until(lambda: bool(app._pending_gates), pilot=pilot)
        assert reached, "approval was never requested within timeout"
        assert app._pending_gates[0].gate == "pr_target"

        await pilot.press("a")

        resolved = await _wait_until(lambda: bool(decisions), pilot=pilot)
        assert resolved, "worker thread never unblocked after approval"
        assert decisions[0].approved is True
        assert decisions[0].approved_gates == frozenset({"pr_target"})
        assert app._pending_gates == []


async def test_approval_rejection_via_keyboard(monkeypatch):
    decisions = []

    def fake_pipeline(issue, **kwargs):
        on_approval_needed = kwargs["on_approval_needed"]
        pending = [PendingApproval(gate="file_count", reason="too many files", detail="6 files")]
        decision = on_approval_needed(pending)
        decisions.append(decision)
        sm = TaskStateMachine(issue_id=issue.id, state=TaskState.FAILED)
        return SimpleNamespace(
            issue=issue, state_machine=sm, triage=None, coder_result=None,
            pr_result=None, error="Rejected by human",
        )

    monkeypatch.setattr("src.codepilot.tui.app.run_full_pipeline_for_issue", fake_pipeline)

    issue = Issue(id="approval-test-2", number=3, title="Needs approval, gets rejected", body="...")
    app = _make_app(issue_source=StaticIssueSource([issue]))

    async with app.run_test() as pilot:
        reached = await _wait_until(lambda: bool(app._pending_gates), pilot=pilot)
        assert reached

        await pilot.press("r")

        resolved = await _wait_until(lambda: bool(decisions), pilot=pilot)
        assert resolved
        assert decisions[0].approved is False
