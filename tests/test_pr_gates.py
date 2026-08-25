from src.codepilot.pr_agent.gates import (
    check_file_count_gate,
    check_pr_target_gate,
    check_retry_gate,
    collect_pending_approvals,
)


def test_pr_target_gate_fires_for_main_and_master():
    assert check_pr_target_gate("main") is not None
    assert check_pr_target_gate("master") is not None
    assert check_pr_target_gate("develop") is None


def test_file_count_gate_threshold():
    assert check_file_count_gate(5) is None  # at threshold - ok
    assert check_file_count_gate(6) is not None


def test_retry_gate_threshold():
    assert check_retry_gate(2) is None
    assert check_retry_gate(3) is not None


def test_collect_pending_approvals_combines_all_gates():
    pending = collect_pending_approvals(base_branch="main", num_files=6, retries=3)
    assert {p.gate for p in pending} == {"pr_target", "file_count", "retry_limit"}


def test_collect_pending_approvals_respects_approved_gates():
    pending = collect_pending_approvals(
        base_branch="main", num_files=6, retries=3, approved_gates=frozenset({"pr_target", "file_count"})
    )
    assert {p.gate for p in pending} == {"retry_limit"}


def test_collect_pending_approvals_empty_when_nothing_trips():
    assert collect_pending_approvals(base_branch="develop", num_files=2, retries=0) == []
