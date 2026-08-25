"""Working memory: task-scoped state, held explicitly and passed by value to
each subagent at spawn time (per the spec's context-engineering rule) rather
than relied on implicitly via shared conversation history.

One `WorkingMemory` instance exists per in-flight issue/task. It is cleared
(dropped) when the task reaches a terminal state (DONE / FAILED) — see
`Orchestrator.finish_task`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkingMemory:
    issue_id: str
    issue_title: str
    issue_body: str

    task_type: str | None = None
    repo_map_path: str | None = None  # path into the deepagents virtual FS, not raw content
    relevant_files: list[str] = field(default_factory=list)  # paths only, never raw content
    current_diff: str | None = None
    test_results: dict[str, Any] | None = None
    retry_count: int = 0

    def record_classification(self, task_type: str) -> None:
        self.task_type = task_type

    def record_relevant_files(self, files: list[str]) -> None:
        self.relevant_files = list(files)

    def record_test_result(self, *, passed: bool, details: dict[str, Any]) -> None:
        self.test_results = {"passed": passed, **details}

    def increment_retry(self) -> int:
        self.retry_count += 1
        return self.retry_count

    def to_subagent_context(self) -> dict[str, Any]:
        """The *only* view of working memory a subagent spawn should receive:
        file paths and small structured facts, never raw file content or the
        full repo map inline (subagents `read_file` on-demand instead).
        """
        return {
            "issue_id": self.issue_id,
            "issue_title": self.issue_title,
            "task_type": self.task_type,
            "repo_map_path": self.repo_map_path,
            "relevant_files": self.relevant_files,
            "retry_count": self.retry_count,
        }
