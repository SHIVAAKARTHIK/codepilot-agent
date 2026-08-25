"""Proves the Coder's retry loop deterministically - using a fake agent
that only fixes the bug on its second call - rather than leaving whether
the retry path gets exercised up to what a real LLM happens to do on a
given run.
"""
from types import SimpleNamespace

from src.codepilot.coder.agent import run_coder_task
from src.codepilot.coder.sandbox import cleanup_sandbox
from src.codepilot.config import settings
from src.codepilot.memory.working import WorkingMemory


class _FakeCoder:
    """Duck-types the `.invoke()` interface `run_coder_task` calls. Applies
    the "fix" directly to the sandbox on its `fix_on_attempt`-th call,
    simulating what a real Coder's edit_file tool call would have done."""

    def __init__(self, sandbox_dir, fix_on_attempt: int):
        self.sandbox_dir = sandbox_dir
        self.fix_on_attempt = fix_on_attempt
        self.calls = 0

    def invoke(self, state):
        self.calls += 1
        if self.calls >= self.fix_on_attempt:
            (self.sandbox_dir / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        return {"messages": [SimpleNamespace(content=f"attempt {self.calls}")], "todos": []}


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_retry_loop_fails_once_then_succeeds(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "calc.py", "def add(a, b):\n    return a - b\n")  # buggy: subtracts instead of adds
    _write(
        repo_root / "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )

    issue_id = "retry-demo-1"
    predicted_sandbox = settings.sandbox_root / f"issue-{issue_id}"
    fake_coder = _FakeCoder(predicted_sandbox, fix_on_attempt=2)

    working_memory = WorkingMemory(issue_id=issue_id, issue_title="add() is subtracting", issue_body="...")
    working_memory.record_classification("bug_fix")
    working_memory.record_relevant_files(["calc.py", "test_calc.py"])

    try:
        result = run_coder_task(
            repo_root=repo_root,
            working_memory=working_memory,
            agent=fake_coder,
            max_retries=3,
        )

        assert fake_coder.calls == 2  # attempt 1 failed, attempt 2 (retry) succeeded
        assert result.retries == 1
        assert result.test_result is not None
        assert result.test_result.passed is True
        assert working_memory.retry_count == 1
        assert "calc.py" in result.diff_text
    finally:
        cleanup_sandbox(predicted_sandbox)


def test_retry_loop_stops_after_max_retries_if_never_fixed(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "calc.py", "def add(a, b):\n    return a - b\n")
    _write(
        repo_root / "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )

    issue_id = "retry-demo-2"
    predicted_sandbox = settings.sandbox_root / f"issue-{issue_id}"
    # fix_on_attempt higher than max_retries+1 -> the bug never gets fixed
    fake_coder = _FakeCoder(predicted_sandbox, fix_on_attempt=99)

    working_memory = WorkingMemory(issue_id=issue_id, issue_title="add() is subtracting", issue_body="...")
    working_memory.record_classification("bug_fix")
    working_memory.record_relevant_files(["calc.py", "test_calc.py"])

    try:
        result = run_coder_task(
            repo_root=repo_root,
            working_memory=working_memory,
            agent=fake_coder,
            max_retries=2,
        )

        assert fake_coder.calls == 3  # initial attempt + 2 retries, then stop
        assert result.retries == 2
        assert result.test_result.passed is False
        assert working_memory.retry_count == 2
    finally:
        cleanup_sandbox(predicted_sandbox)


def test_no_retry_needed_when_first_attempt_passes(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "calc.py", "def add(a, b):\n    return a + b\n")  # already correct
    _write(
        repo_root / "test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )

    issue_id = "retry-demo-3"
    predicted_sandbox = settings.sandbox_root / f"issue-{issue_id}"
    fake_coder = _FakeCoder(predicted_sandbox, fix_on_attempt=1)

    working_memory = WorkingMemory(issue_id=issue_id, issue_title="n/a", issue_body="...")
    working_memory.record_classification("bug_fix")
    working_memory.record_relevant_files(["calc.py", "test_calc.py"])

    try:
        result = run_coder_task(
            repo_root=repo_root, working_memory=working_memory, agent=fake_coder, max_retries=3
        )

        assert fake_coder.calls == 1
        assert result.retries == 0
        assert result.test_result.passed is True
        assert working_memory.retry_count == 0
    finally:
        cleanup_sandbox(predicted_sandbox)
