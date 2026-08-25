"""PR Agent: opens a structured pull request once the Coder/Test Agent's
changes pass verification (Component 6).

Not itself an LLM agent - branch naming, commit messages, and PR bodies
are all deterministically formatted (formatting.py), and the four HITL
gates are deterministic checks (gates.py). There's no "creative" decision
left for an LLM to make here that isn't better done as structured code,
consistent with the rest of the pipeline's "LLM for judgment, code for
mechanics" split.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.codepilot.coder.agent import CoderResult
from src.codepilot.github_client import GitHubClient, MergeConflict
from src.codepilot.orchestrator.issue import Issue
from src.codepilot.pr_agent.formatting import branch_name, commit_message, pr_body, pr_title
from src.codepilot.pr_agent.gates import PendingApproval, collect_pending_approvals

DEFAULT_LABELS = ["codepilot-generated", "needs-review"]


@dataclass
class PRResult:
    status: str  # "PR_OPENED" | "PENDING_APPROVAL" | "FAILED"
    pr_url: str | None = None
    pr_number: int | None = None
    branch: str | None = None
    pending_approvals: list[PendingApproval] = field(default_factory=list)
    error: str | None = None


def open_pull_request(
    *,
    github_client: GitHubClient,
    issue: Issue,
    coder_result: CoderResult,
    approach_summary: str,
    what_changed: list[str],
    why: str,
    approved_gates: frozenset[str] = frozenset(),
    labels: list[str] | None = None,
    reviewer: str | None = None,
) -> PRResult:
    """Checks all 4 HITL gates first; if any are un-approved, returns
    PENDING_APPROVAL without touching GitHub at all - no branch, no
    commit, no PR. Only once every gate is clear (or pre-approved via
    `approved_gates`) does it actually write anything."""
    base_branch = github_client.get_default_branch()
    num_files = len(coder_result.changed_files)
    retries = coder_result.retries

    pending = collect_pending_approvals(
        base_branch=base_branch, num_files=num_files, retries=retries, approved_gates=approved_gates
    )
    if pending:
        return PRResult(status="PENDING_APPROVAL", pending_approvals=pending)

    branch = branch_name(issue.number, issue.title)
    files = _read_changed_files(coder_result)
    message = commit_message(issue_number=issue.number, summary=issue.title, what_changed=what_changed, why=why)

    try:
        github_client.commit_files_to_branch(branch=branch, files=files, message=message)
    except MergeConflict as exc:
        # Spec: do not attempt to resolve automatically - surface it.
        return PRResult(status="FAILED", branch=branch, error=str(exc))

    issue_url = f"https://github.com/{github_client.repo.full_name}/issues/{issue.number}"
    pr = github_client.open_pull_request(
        branch=branch,
        base=base_branch,
        title=pr_title(issue.title),
        body=pr_body(
            issue_number=issue.number,
            issue_url=issue_url,
            approach=approach_summary,
            files_changed=coder_result.changed_files,
            test_summary=_format_test_summary(coder_result),
        ),
        labels=labels or DEFAULT_LABELS,
        reviewer=reviewer if reviewer is not None else issue.reporter,
    )

    return PRResult(status="PR_OPENED", pr_url=pr.html_url, pr_number=pr.number, branch=branch)


def _read_changed_files(coder_result: CoderResult) -> dict[str, str]:
    files: dict[str, str] = {}
    for rel_path in coder_result.changed_files:
        full_path = coder_result.sandbox_dir / rel_path
        if full_path.is_file():
            files[rel_path] = full_path.read_text(encoding="utf-8", errors="ignore")
    return files


def _format_test_summary(coder_result: CoderResult) -> str:
    tr = coder_result.test_result
    if tr is None:
        return "(no test run recorded)"
    if tr.no_tests_collected:
        return "No tests were found to run for this change."
    counts_str = ", ".join(f"{v} {k}" for k, v in tr.counts.items()) or "no summary parsed"
    status = "PASSED" if tr.passed else "FAILED"
    retry_note = ""
    if coder_result.retries:
        plural = "y" if coder_result.retries == 1 else "ies"
        retry_note = f" after {coder_result.retries} retr{plural}"
    return f"{status}{retry_note}: {counts_str}"
