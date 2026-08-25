"""Human-in-the-loop approval gates (Component 6).

Detection is deterministic and unit-testable. Actually *pausing* for a
human's live decision is the TUI's job (Phase 8) - until then,
`open_pull_request` refuses to perform a gated action rather than silently
proceeding past it or blocking it forever, mirroring the same honest gap
documented for the Coder's guardrails in Phase 4 (BUILD_PLAN.md).
"""
from __future__ import annotations

from dataclasses import dataclass

PROTECTED_BRANCHES = {"main", "master"}
DEFAULT_FILE_COUNT_THRESHOLD = 5
DEFAULT_RETRY_THRESHOLD = 2


@dataclass(frozen=True)
class PendingApproval:
    gate: str
    reason: str
    detail: str


def check_pr_target_gate(base_branch: str) -> PendingApproval | None:
    if base_branch in PROTECTED_BRANCHES:
        return PendingApproval(
            gate="pr_target",
            reason="Opening a PR to main/master is irreversible without a revert.",
            detail=f"base branch: {base_branch}",
        )
    return None


def check_file_count_gate(
    num_files: int, *, threshold: int = DEFAULT_FILE_COUNT_THRESHOLD
) -> PendingApproval | None:
    if num_files > threshold:
        return PendingApproval(
            gate="file_count",
            reason=f"Commit touches more than {threshold} files - risk of unintended scope.",
            detail=f"{num_files} files changed",
        )
    return None


def check_retry_gate(retries: int, *, threshold: int = DEFAULT_RETRY_THRESHOLD) -> PendingApproval | None:
    if retries > threshold:
        return PendingApproval(
            gate="retry_limit",
            reason=f"More than {threshold} failed test runs - risk of an infinite retry loop.",
            detail=f"{retries} retries",
        )
    return None


def collect_pending_approvals(
    *, base_branch: str, num_files: int, retries: int, approved_gates: frozenset[str] = frozenset()
) -> list[PendingApproval]:
    """All gates a PR attempt currently trips, minus any already approved
    (e.g. by a human via the TUI, or by a test/demo standing in for one)."""
    checks = [
        check_pr_target_gate(base_branch),
        check_file_count_gate(num_files),
        check_retry_gate(retries),
    ]
    return [c for c in checks if c is not None and c.gate not in approved_gates]
