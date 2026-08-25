"""Ties every phase's pieces into one full run: issue -> triage -> explore
-> code+test -> PR, driving the Component 1 state machine end to end.

This is what the TUI (Phase 8) drives per issue. It's deliberately a plain
function, not itself an agent - orchestration across already-built agents
is mechanical control flow, not something that benefits from another LLM
call, consistent with the "LLM for judgment, code for mechanics" split
used throughout this codebase.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.codepilot.coder.agent import CoderResult, run_coder_task
from src.codepilot.github_client import GitHubClient
from src.codepilot.memory.episodic import EpisodicMemory, TaskLogEntry
from src.codepilot.memory.semantic import SemanticMemory
from src.codepilot.orchestrator.agent import TriageResult, run_triage
from src.codepilot.orchestrator.issue import Issue
from src.codepilot.orchestrator.state_machine import TaskState, TaskStateMachine
from src.codepilot.pr_agent.agent import PRResult, open_pull_request
from src.codepilot.pr_agent.gates import PendingApproval
from src.codepilot.repo_explorer.explorer import RepoExplorer
from src.codepilot.skills.registry import load as load_skill


@dataclass
class ApprovalDecision:
    approved: bool
    approved_gates: frozenset[str] = frozenset()


@dataclass
class PipelineResult:
    issue: Issue
    state_machine: TaskStateMachine
    triage: TriageResult | None = None
    coder_result: CoderResult | None = None
    pr_result: PRResult | None = None
    error: str | None = None


ProgressCallback = Callable[[str, str], None]  # (stage, message)
ApprovalCallback = Callable[[list[PendingApproval]], ApprovalDecision]


def run_full_pipeline_for_issue(
    issue: Issue,
    *,
    repo_root: Path,
    repo_explorer: RepoExplorer,
    episodic_memory: EpisodicMemory,
    semantic_memory: SemanticMemory,
    github_client: GitHubClient | None,
    repo_id: str,
    on_progress: ProgressCallback | None = None,
    on_approval_needed: ApprovalCallback | None = None,
    llm=None,
    triage_agent=None,
    coder_agent=None,
) -> PipelineResult:
    """Runs one issue all the way through. `github_client=None` stops
    cleanly right before the PR step (dry run) - useful for demos/tests
    that don't want a real GitHub write. `on_approval_needed`, if given,
    is called (and may block) whenever the PR Agent returns
    PENDING_APPROVAL; without it, a pending approval is treated as a
    failure rather than silently skipped or silently forced through.
    """

    def progress(stage: str, message: str) -> None:
        if on_progress:
            on_progress(stage, message)

    progress("TRIAGE", f"Classifying issue #{issue.number}: {issue.title}")
    triage = run_triage(issue, llm=llm, agent=triage_agent)
    result = PipelineResult(issue=issue, state_machine=triage.state_machine, triage=triage)
    progress(
        "TRIAGE",
        f"Classified as {triage.classification.task_type.value} "
        f"(confidence={triage.classification.confidence:.2f})",
    )

    progress("EXPLORE", "Selecting relevant files...")
    query = f"{issue.title}\n{issue.body}"
    scored_files = repo_explorer.select_relevant_files(query)
    triage.working_memory.record_relevant_files([f.path for f in scored_files])
    progress("EXPLORE", f"Selected {len(scored_files)} relevant file(s): {[f.path for f in scored_files]}")

    triage.state_machine.transition(TaskState.IMPLEMENTING, reason="repo exploration complete")

    skill = load_skill(triage.classification.task_type.value)
    progress("CODE", f"Coder implementing fix (skill: {skill.name})...")
    coder_result = run_coder_task(
        repo_root=repo_root,
        working_memory=triage.working_memory,
        skill=skill,
        semantic_memory=semantic_memory,
        repo_id=repo_id,
        agent=coder_agent,
    )
    result.coder_result = coder_result
    progress(
        "CODE",
        f"Coder finished - retries={coder_result.retries}, changed_files={coder_result.changed_files}",
    )

    triage.state_machine.transition(TaskState.TESTING, reason="verifying Coder's changes")

    test_result = coder_result.test_result
    test_ok = test_result is not None and (test_result.passed or test_result.no_tests_collected)
    if not test_ok:
        triage.state_machine.fail("tests failed after max retries")
        result.error = "Tests failed after max retries"
        progress("FAILED", result.error)
        _log_episode(episodic_memory, issue, triage, coder_result, outcome="FAILED")
        return result

    if github_client is None:
        progress("DONE", "No GitHub client configured - stopping before the PR step (dry run).")
        triage.state_machine.transition(TaskState.PR_OPENED, reason="skipped (dry run, no github client)")
        triage.state_machine.transition(TaskState.DONE, reason="dry run complete")
        _log_episode(episodic_memory, issue, triage, coder_result, outcome="DONE")
        return result

    approved_gates: frozenset[str] = frozenset()
    while True:
        progress("PR", "Opening pull request...")
        pr_result = open_pull_request(
            github_client=github_client,
            issue=issue,
            coder_result=coder_result,
            approach_summary=coder_result.final_message[:500],
            what_changed=[f"Updated {f}" for f in coder_result.changed_files],
            why="Fixes the reported issue.",
            approved_gates=approved_gates,
            semantic_memory=semantic_memory,
            task_type=triage.classification.task_type.value,
        )
        result.pr_result = pr_result

        if pr_result.status == "PENDING_APPROVAL":
            progress("APPROVAL", f"{len(pr_result.pending_approvals)} gate(s) need approval")
            if on_approval_needed is None:
                result.error = "Approval required but no approval handler was configured"
                triage.state_machine.fail(result.error)
                progress("FAILED", result.error)
                _log_episode(episodic_memory, issue, triage, coder_result, outcome="FAILED")
                return result

            decision = on_approval_needed(pr_result.pending_approvals)
            if not decision.approved:
                triage.state_machine.fail("human rejected a pending approval")
                result.error = "Rejected by human"
                progress("FAILED", result.error)
                _log_episode(episodic_memory, issue, triage, coder_result, outcome="FAILED")
                return result

            approved_gates = approved_gates | decision.approved_gates
            continue

        if pr_result.status == "FAILED":
            triage.state_machine.fail(pr_result.error or "PR Agent failed")
            result.error = pr_result.error
            progress("FAILED", result.error or "PR Agent failed")
            _log_episode(episodic_memory, issue, triage, coder_result, outcome="FAILED")
            return result

        triage.state_machine.transition(TaskState.PR_OPENED, reason="PR opened")
        triage.state_machine.transition(TaskState.DONE, reason="pipeline complete")
        progress("DONE", f"PR opened: {pr_result.pr_url}")
        _log_episode(episodic_memory, issue, triage, coder_result, outcome="DONE")
        return result


def _log_episode(
    episodic_memory: EpisodicMemory,
    issue: Issue,
    triage: TriageResult,
    coder_result: CoderResult | None,
    *,
    outcome: str,
) -> None:
    episodic_memory.log_task(
        TaskLogEntry(
            issue_id=issue.id,
            task_type=triage.classification.task_type.value,
            files_modified=coder_result.changed_files if coder_result else [],
            outcome=outcome,
            duration_seconds=0.0,
        )
    )
