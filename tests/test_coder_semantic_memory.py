"""Proves the Phase 7 'done when' requirement deterministically: given a
past lesson recorded for a similar issue, a new task's Coder prompt
visibly includes it - using a recording fake agent so this doesn't depend
on any real LLM call.
"""
from types import SimpleNamespace

from src.codepilot.coder.agent import run_coder_task
from src.codepilot.coder.sandbox import cleanup_sandbox
from src.codepilot.config import settings
from src.codepilot.memory.semantic import SemanticMemory
from src.codepilot.memory.working import WorkingMemory


class _RecordingCoder:
    """Records every prompt it's invoked with; makes no sandbox changes -
    just enough to prove what context the Coder actually received."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def invoke(self, state):
        self.prompts.append(state["messages"][0]["content"])
        return {"messages": [SimpleNamespace(content="noted")], "todos": []}


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_run_coder_task_injects_retrieved_lesson(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "calc.py", "def add(a, b):\n    return a + b\n")

    semantic_memory = SemanticMemory(persist_dir=tmp_path / "chroma")
    semantic_memory.record_lesson(
        repo="acme/demo",
        task_type="bug_fix",
        issue_summary="divide() crashes on division by zero",
        approach="Added a check for b == 0 and returned None instead of raising.",
        files_changed=["calc.py"],
    )

    issue_id = "semantic-demo-1"
    working_memory = WorkingMemory(
        issue_id=issue_id,
        issue_title="modulo() crashes on division by zero",
        issue_body="calc.modulo(a, b) raises ZeroDivisionError when b is 0, similar to the earlier divide() bug.",
    )
    working_memory.record_classification("bug_fix")
    working_memory.record_relevant_files(["calc.py"])

    coder = _RecordingCoder()
    predicted_sandbox = settings.sandbox_root / f"issue-{issue_id}"
    try:
        result = run_coder_task(
            repo_root=repo_root,
            working_memory=working_memory,
            agent=coder,
            semantic_memory=semantic_memory,
            repo_id="acme/demo",
        )

        assert len(coder.prompts) == 1
        prompt = coder.prompts[0]
        assert "divide() crashes on division by zero" in prompt
        assert "Added a check for b == 0" in prompt
        assert len(result.lessons_used) == 1
        assert result.lessons_used[0].issue_summary == "divide() crashes on division by zero"
    finally:
        cleanup_sandbox(predicted_sandbox)


def test_run_coder_task_without_semantic_memory_has_no_lessons_block(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "calc.py", "def add(a, b):\n    return a + b\n")

    issue_id = "semantic-demo-2"
    working_memory = WorkingMemory(issue_id=issue_id, issue_title="x", issue_body="x")
    working_memory.record_classification("bug_fix")
    working_memory.record_relevant_files(["calc.py"])

    coder = _RecordingCoder()
    predicted_sandbox = settings.sandbox_root / f"issue-{issue_id}"
    try:
        result = run_coder_task(repo_root=repo_root, working_memory=working_memory, agent=coder)
        assert result.lessons_used == []
        assert "Lessons from similar past issues" not in coder.prompts[0]
    finally:
        cleanup_sandbox(predicted_sandbox)
