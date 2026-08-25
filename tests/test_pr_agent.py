from types import SimpleNamespace

from src.codepilot.coder.agent import CoderResult
from src.codepilot.github_client import MergeConflict
from src.codepilot.orchestrator.issue import Issue
from src.codepilot.pr_agent.agent import open_pull_request
from src.codepilot.test_agent.runner import TestResult


class _FakeGitHubClient:
    """Duck-types GitHubClient's write methods so PR Agent logic can be
    tested without any real network call."""

    def __init__(self, *, default_branch="feature-base", raise_conflict=False):
        self.default_branch = default_branch
        self.raise_conflict = raise_conflict
        self.committed = None
        self.opened_pr = None
        self.repo = SimpleNamespace(full_name="acme/demo")

    def get_default_branch(self):
        return self.default_branch

    def commit_files_to_branch(self, *, branch, files, message):
        if self.raise_conflict:
            raise MergeConflict("branch diverged")
        self.committed = {"branch": branch, "files": files, "message": message}
        return "deadbeef"

    def open_pull_request(self, *, branch, base, title, body, labels, reviewer):
        self.opened_pr = {
            "branch": branch,
            "base": base,
            "title": title,
            "body": body,
            "labels": labels,
            "reviewer": reviewer,
        }
        return SimpleNamespace(html_url="https://github.com/acme/demo/pull/1", number=1)


def _make_coder_result(tmp_path, *, changed_files, retries=0, passed=True):
    for rel in changed_files:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# fixed {rel}\n", encoding="utf-8")
    return CoderResult(
        sandbox_dir=tmp_path,
        diff_text="--- a/x\n+++ b/x\n",
        changed_files=list(changed_files),
        retries=retries,
        test_result=TestResult(
            passed=passed, no_tests_collected=False, exit_code=0 if passed else 1, counts={"passed": 1}
        ),
    )


def _issue(**overrides):
    defaults = {"id": "1", "number": 1, "title": "Fix null pointer", "body": "...", "reporter": "alice"}
    defaults.update(overrides)
    return Issue(**defaults)


def test_pending_approval_when_base_is_main(tmp_path):
    client = _FakeGitHubClient(default_branch="main")
    coder_result = _make_coder_result(tmp_path, changed_files=["a.py"])

    result = open_pull_request(
        github_client=client,
        issue=_issue(),
        coder_result=coder_result,
        approach_summary="fixed it",
        what_changed=["fixed null check"],
        why="prevents crash",
    )

    assert result.status == "PENDING_APPROVAL"
    assert any(p.gate == "pr_target" for p in result.pending_approvals)
    assert client.committed is None  # nothing written to GitHub
    assert client.opened_pr is None


def test_pending_approval_when_more_than_5_files(tmp_path):
    client = _FakeGitHubClient(default_branch="develop")
    coder_result = _make_coder_result(tmp_path, changed_files=[f"f{i}.py" for i in range(6)])

    result = open_pull_request(
        github_client=client, issue=_issue(), coder_result=coder_result,
        approach_summary="x", what_changed=["x"], why="x",
    )

    assert result.status == "PENDING_APPROVAL"
    assert any(p.gate == "file_count" for p in result.pending_approvals)
    assert client.committed is None


def test_pending_approval_when_retries_exceed_threshold(tmp_path):
    client = _FakeGitHubClient(default_branch="develop")
    coder_result = _make_coder_result(tmp_path, changed_files=["a.py"], retries=3)

    result = open_pull_request(
        github_client=client, issue=_issue(), coder_result=coder_result,
        approach_summary="x", what_changed=["x"], why="x",
    )

    assert result.status == "PENDING_APPROVAL"
    assert any(p.gate == "retry_limit" for p in result.pending_approvals)


def test_proceeds_when_gates_pre_approved(tmp_path):
    client = _FakeGitHubClient(default_branch="main")  # would normally gate
    coder_result = _make_coder_result(tmp_path, changed_files=["a.py"])

    result = open_pull_request(
        github_client=client,
        issue=_issue(),
        coder_result=coder_result,
        approach_summary="fixed it",
        what_changed=["fixed null check"],
        why="prevents crash",
        approved_gates=frozenset({"pr_target"}),
    )

    assert result.status == "PR_OPENED"
    assert result.pr_url == "https://github.com/acme/demo/pull/1"
    assert client.committed["branch"] == "codepilot/issue-1-fix-null-pointer"
    assert "Closes #1" in client.committed["message"]
    assert client.opened_pr["labels"] == ["codepilot-generated", "needs-review"]
    assert client.opened_pr["reviewer"] == "alice"  # defaults to issue reporter


def test_merge_conflict_results_in_failed_not_retry(tmp_path):
    client = _FakeGitHubClient(default_branch="develop", raise_conflict=True)
    coder_result = _make_coder_result(tmp_path, changed_files=["a.py"])

    result = open_pull_request(
        github_client=client, issue=_issue(), coder_result=coder_result,
        approach_summary="x", what_changed=["x"], why="x",
    )

    assert result.status == "FAILED"
    assert "diverged" in result.error
    assert client.opened_pr is None  # never got to opening a PR


def test_explicit_reviewer_overrides_issue_reporter(tmp_path):
    client = _FakeGitHubClient(default_branch="develop")
    coder_result = _make_coder_result(tmp_path, changed_files=["a.py"])

    open_pull_request(
        github_client=client,
        issue=_issue(reporter="alice"),
        coder_result=coder_result,
        approach_summary="x",
        what_changed=["x"],
        why="x",
        reviewer="bob",
    )

    assert client.opened_pr["reviewer"] == "bob"
