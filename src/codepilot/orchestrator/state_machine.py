"""The per-task state machine required by the assignment spec:

    TRIAGED -> EXPLORING -> IMPLEMENTING -> TESTING -> PR_OPENED -> DONE | FAILED

This is a real, enforced state machine (illegal transitions raise) rather
than prose in a prompt, so the Orchestrator's task lifecycle is inspectable
and testable independent of the LLM.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum


class TaskState(str, Enum):
    TRIAGED = "TRIAGED"
    EXPLORING = "EXPLORING"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    PR_OPENED = "PR_OPENED"
    DONE = "DONE"
    FAILED = "FAILED"


TERMINAL_STATES = {TaskState.DONE, TaskState.FAILED}

# TESTING -> IMPLEMENTING is the Coder/Test-agent retry loop (max retries
# enforced by the caller, not by the state machine itself).
_ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.TRIAGED: {TaskState.EXPLORING, TaskState.FAILED},
    TaskState.EXPLORING: {TaskState.IMPLEMENTING, TaskState.FAILED},
    TaskState.IMPLEMENTING: {TaskState.TESTING, TaskState.FAILED},
    TaskState.TESTING: {TaskState.IMPLEMENTING, TaskState.PR_OPENED, TaskState.FAILED},
    TaskState.PR_OPENED: {TaskState.DONE, TaskState.FAILED},
    TaskState.DONE: set(),
    TaskState.FAILED: set(),
}


class InvalidTransition(RuntimeError):
    def __init__(self, current: TaskState, target: TaskState) -> None:
        super().__init__(f"Cannot transition {current.value} -> {target.value}")
        self.current = current
        self.target = target


@dataclass
class TaskStateMachine:
    """Tracks one issue's journey through the pipeline, with full history."""

    issue_id: str
    state: TaskState = TaskState.TRIAGED
    history: list[tuple[TaskState, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.history:
            self.history.append((self.state, _now()))

    def transition(self, target: TaskState, *, reason: str = "") -> None:
        allowed = _ALLOWED_TRANSITIONS[self.state]
        if target not in allowed:
            raise InvalidTransition(self.state, target)
        self.state = target
        self.history.append((target, _now()))
        if reason:
            self.history[-1] = (target, f"{_now()} - {reason}")

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def fail(self, reason: str) -> None:
        self.transition(TaskState.FAILED, reason=reason)


def _now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")
