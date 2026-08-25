"""Tests for the full pipeline glue (orchestrator/pipeline.py): state
transitions, episodic logging, and the approval loop. Classification,
coding, and PR-opening are already thoroughly tested in isolation
elsewhere (Phases 1/4/5/6) - these tests fake all three so what's actually
being proven here is the *orchestration* wiring, not re-proving those
pieces work.
"""
from types import SimpleNamespace

from src.codepilot.coder.sandbox import cleanup_sandbox
from src.codepilot.config import settings
from src.codepilot.github_client import MergeConflict
from src.codepilot.memory.episodic import EpisodicMemory
from src.codepilot.memory.semantic import SemanticMemory
from src.codepilot.orchestrator.classifier import IssueClassification, TaskType
from src.codepilot.orchestrator.issue import Issue
from src.codepilot.orchestrator.pipeline import ApprovalDecision, run_full_pipeline_for_issue
from src.codepilot.orchestrator.state_machine import TaskState
from src.codepilot.repo_explorer.explorer import RepoExplorer


class _FakeLLM:
    def __init__(self, classification: IssueClassification) -> None:
        self._classification = classification

    def with_structured_output(self, schema):
        return SimpleNamespace(invoke=lambda prompt: self._classification)


class _FakeTriageAgent:
    def invoke(self, state):
        return {
            "messages": [SimpleNamespace(content="Plan: fix the bug.")],
            "todos": [{"content": "reproduce", "status": "completed"}],
        }


class _FakeCoderThatFixesImmediately:
    def __init__(self, sandbox_dir) -> None:
        self.sandbox_dir = sandbox_dir
        self.calls = 0

    def invoke(self, state):
        self.calls += 1
        (self.sandbox_dir / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        return {"messages": [SimpleNamespace(content="Fixed add().")], "todos": []}


class _FakeCoderThatNeverFixes:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, state):
        self.calls += 1
        return {"messages": [SimpleNamespace(content="I tried.")], "todos": []}


class _FakeGitHubClient:
    def __init__(self, *, default_branch="develop", raise_conflict=False) -> None:
        self.default_branch = default_branch
        self.raise_conflict = raise_conflict
        self.committed = None
        self.repo = SimpleNamespace(full_name="acme/demo")

    def get_default_branch(self):
        return self.default_branch

    def commit_files_to_branch(self, *, branch, files, message):
        if self.raise_conflict:
            raise MergeConflict("branch diverged")
        self.committed = {"branch": branch, "files": files}
        return "deadbeef"

    def open_pull_request(self, *, branch, base, title, body, labels, reviewer):
        return SimpleNamespace(html_url="https://github.com/acme/demo/pull/1", number=1)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo_explorer(tmp_path, *, with_test_file=False):
    repo_root = tmp_path / "repo"
    _write(repo_root / "calc.py", "def add(a, b):\n    return a - b\n")  # buggy
    if with_test_file:
        _write(
            repo_root / "test_calc.py",
            "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        )
    explorer = RepoExplorer(repo_root, cache_dir=tmp_path / "repo_map_cache")
    explorer.build_or_load()
    return explorer, repo_root


_CLASSIFICATION = IssueClassification(task_type=TaskType.BUG_FIX, confidence=0.95, reasoning="looks like a bug")


def test_pipeline_dry_run_reaches_done(tmp_path):
    explorer, repo_root = _make_repo_explorer(tmp_path)
    episodic = EpisodicMemory(persist_path=tmp_path / "episodic.json")
    semantic = SemanticMemory(persist_dir=tmp_path / "chroma")

    issue = Issue(id="pipe-1", number=1, title="add() is wrong", body="calc.add(a,b) returns the wrong value")
    predicted_sandbox = settings.sandbox_root / f"issue-{issue.id}"
    coder = _FakeCoderThatFixesImmediately(predicted_sandbox)

    try:
        result = run_full_pipeline_for_issue(
            issue,
            repo_root=repo_root,
            repo_explorer=explorer,
            episodic_memory=episodic,
            semantic_memory=semantic,
            github_client=None,  # dry run - stop before the PR step
            repo_id="acme/demo",
            llm=_FakeLLM(_CLASSIFICATION),
            triage_agent=_FakeTriageAgent(),
            coder_agent=coder,
        )

        assert result.state_machine.state == TaskState.DONE
        assert result.error is None
        assert coder.calls == 1
        assert len(episodic.tasks) == 1
        assert episodic.tasks[0].outcome == "DONE"
    finally:
        cleanup_sandbox(predicted_sandbox)


def test_pipeline_test_failure_leads_to_failed(tmp_path):
    explorer, repo_root = _make_repo_explorer(tmp_path, with_test_file=True)
    episodic = EpisodicMemory(persist_path=tmp_path / "episodic.json")
    semantic = SemanticMemory(persist_dir=tmp_path / "chroma")

    issue = Issue(id="pipe-2", number=2, title="add() is wrong", body="calc.add(a,b) returns the wrong value")
    predicted_sandbox = settings.sandbox_root / f"issue-{issue.id}"
    coder = _FakeCoderThatNeverFixes()

    try:
        result = run_full_pipeline_for_issue(
            issue,
            repo_root=repo_root,
            repo_explorer=explorer,
            episodic_memory=episodic,
            semantic_memory=semantic,
            github_client=None,
            repo_id="acme/demo",
            llm=_FakeLLM(_CLASSIFICATION),
            triage_agent=_FakeTriageAgent(),
            coder_agent=coder,
        )

        assert result.state_machine.state == TaskState.FAILED
        assert "Tests failed" in result.error
        assert episodic.tasks[0].outcome == "FAILED"
    finally:
        cleanup_sandbox(predicted_sandbox)


def test_pipeline_pending_approval_then_approved_reaches_done(tmp_path):
    explorer, repo_root = _make_repo_explorer(tmp_path)
    episodic = EpisodicMemory(persist_path=tmp_path / "episodic.json")
    semantic = SemanticMemory(persist_dir=tmp_path / "chroma")

    issue = Issue(id="pipe-3", number=3, title="add() is wrong", body="calc.add(a,b) returns the wrong value")
    predicted_sandbox = settings.sandbox_root / f"issue-{issue.id}"
    coder = _FakeCoderThatFixesImmediately(predicted_sandbox)
    github_client = _FakeGitHubClient(default_branch="main")  # trips the pr_target gate

    approvals_seen = []

    def approve(pending):
        approvals_seen.append(pending)
        return ApprovalDecision(approved=True, approved_gates=frozenset(p.gate for p in pending))

    try:
        result = run_full_pipeline_for_issue(
            issue,
            repo_root=repo_root,
            repo_explorer=explorer,
            episodic_memory=episodic,
            semantic_memory=semantic,
            github_client=github_client,
            repo_id="acme/demo",
            llm=_FakeLLM(_CLASSIFICATION),
            triage_agent=_FakeTriageAgent(),
            coder_agent=coder,
            on_approval_needed=approve,
        )

        assert len(approvals_seen) == 1
        assert approvals_seen[0][0].gate == "pr_target"
        assert result.state_machine.state == TaskState.DONE
        assert result.pr_result.status == "PR_OPENED"
        assert episodic.tasks[0].outcome == "DONE"
    finally:
        cleanup_sandbox(predicted_sandbox)


def test_pipeline_pending_approval_rejected_leads_to_failed(tmp_path):
    explorer, repo_root = _make_repo_explorer(tmp_path)
    episodic = EpisodicMemory(persist_path=tmp_path / "episodic.json")
    semantic = SemanticMemory(persist_dir=tmp_path / "chroma")

    issue = Issue(id="pipe-4", number=4, title="add() is wrong", body="calc.add(a,b) returns the wrong value")
    predicted_sandbox = settings.sandbox_root / f"issue-{issue.id}"
    coder = _FakeCoderThatFixesImmediately(predicted_sandbox)
    github_client = _FakeGitHubClient(default_branch="main")

    try:
        result = run_full_pipeline_for_issue(
            issue,
            repo_root=repo_root,
            repo_explorer=explorer,
            episodic_memory=episodic,
            semantic_memory=semantic,
            github_client=github_client,
            repo_id="acme/demo",
            llm=_FakeLLM(_CLASSIFICATION),
            triage_agent=_FakeTriageAgent(),
            coder_agent=coder,
            on_approval_needed=lambda pending: ApprovalDecision(approved=False),
        )

        assert result.state_machine.state == TaskState.FAILED
        assert result.error == "Rejected by human"
        assert result.pr_result is None or result.pr_result.status == "PENDING_APPROVAL"
        assert github_client.committed is None  # never wrote to GitHub
    finally:
        cleanup_sandbox(predicted_sandbox)


def test_pipeline_pending_approval_without_handler_fails_safe(tmp_path):
    explorer, repo_root = _make_repo_explorer(tmp_path)
    episodic = EpisodicMemory(persist_path=tmp_path / "episodic.json")
    semantic = SemanticMemory(persist_dir=tmp_path / "chroma")

    issue = Issue(id="pipe-5", number=5, title="add() is wrong", body="calc.add(a,b) returns the wrong value")
    predicted_sandbox = settings.sandbox_root / f"issue-{issue.id}"
    coder = _FakeCoderThatFixesImmediately(predicted_sandbox)
    github_client = _FakeGitHubClient(default_branch="main")

    try:
        result = run_full_pipeline_for_issue(
            issue,
            repo_root=repo_root,
            repo_explorer=explorer,
            episodic_memory=episodic,
            semantic_memory=semantic,
            github_client=github_client,
            repo_id="acme/demo",
            llm=_FakeLLM(_CLASSIFICATION),
            triage_agent=_FakeTriageAgent(),
            coder_agent=coder,
            # no on_approval_needed - must not silently proceed
        )

        assert result.state_machine.state == TaskState.FAILED
        assert "Approval required" in result.error
        assert github_client.committed is None
    finally:
        cleanup_sandbox(predicted_sandbox)


def test_pipeline_merge_conflict_leads_to_failed(tmp_path):
    explorer, repo_root = _make_repo_explorer(tmp_path)
    episodic = EpisodicMemory(persist_path=tmp_path / "episodic.json")
    semantic = SemanticMemory(persist_dir=tmp_path / "chroma")

    issue = Issue(id="pipe-6", number=6, title="add() is wrong", body="calc.add(a,b) returns the wrong value")
    predicted_sandbox = settings.sandbox_root / f"issue-{issue.id}"
    coder = _FakeCoderThatFixesImmediately(predicted_sandbox)
    github_client = _FakeGitHubClient(default_branch="develop", raise_conflict=True)

    try:
        result = run_full_pipeline_for_issue(
            issue,
            repo_root=repo_root,
            repo_explorer=explorer,
            episodic_memory=episodic,
            semantic_memory=semantic,
            github_client=github_client,
            repo_id="acme/demo",
            llm=_FakeLLM(_CLASSIFICATION),
            triage_agent=_FakeTriageAgent(),
            coder_agent=coder,
        )

        assert result.state_machine.state == TaskState.FAILED
        assert "diverged" in result.error
    finally:
        cleanup_sandbox(predicted_sandbox)
