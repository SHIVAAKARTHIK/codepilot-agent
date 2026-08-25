"""Tracks issue IDs currently being worked, so the polling loop never
double-processes an issue that's already mid-flight.

Lives for the lifetime of the running Orchestrator process. This is the
Orchestrator's own session-level bookkeeping across *all* tasks - distinct
from a single task's `WorkingMemory` (src/codepilot/memory/working.py),
which is scoped to one issue and cleared when that issue finishes.
"""
from __future__ import annotations


class InProgressTracker:
    def __init__(self) -> None:
        self._ids: set[str] = set()

    def mark(self, issue_id: str) -> None:
        self._ids.add(issue_id)

    def unmark(self, issue_id: str) -> None:
        self._ids.discard(issue_id)

    def is_in_progress(self, issue_id: str) -> bool:
        return issue_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)
