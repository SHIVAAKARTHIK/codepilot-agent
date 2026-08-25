"""Offline issue source for demoing/testing the TUI without real GitHub
credentials: yields a fixed list of issues once, then nothing further.
Matches `IssuePoller`'s `poll_once()` interface so the App doesn't need to
special-case where issues come from.
"""
from __future__ import annotations

from src.codepilot.orchestrator.issue import Issue


class StaticIssueSource:
    def __init__(self, issues: list[Issue]) -> None:
        self._remaining = list(issues)

    def poll_once(self) -> list[Issue]:
        issues, self._remaining = self._remaining, []
        return issues
