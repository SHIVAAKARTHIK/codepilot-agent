"""Component 1's polling loop: poll GitHub for candidate issues, skip ones
already in-progress or recently failed, hand fresh ones off for triage.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from src.codepilot.config import settings
from src.codepilot.github_client import GitHubClient
from src.codepilot.memory.episodic import EpisodicMemory
from src.codepilot.orchestrator.in_progress import InProgressTracker
from src.codepilot.orchestrator.issue import Issue


class IssuePoller:
    def __init__(
        self,
        *,
        github_client: GitHubClient | None = None,
        in_progress: InProgressTracker | None = None,
        episodic: EpisodicMemory | None = None,
        complexity_threshold: int | None = None,
    ) -> None:
        self.github_client = github_client or GitHubClient()
        self.in_progress = in_progress or InProgressTracker()
        self.episodic = episodic or EpisodicMemory()
        self.complexity_threshold = complexity_threshold or settings.complexity_threshold

    def poll_once(self) -> list[Issue]:
        """One polling cycle: fetch candidates, drop already-in-progress and
        recently-failed issues, mark the rest in-progress, and return them
        for the caller to hand to the Orchestrator for triage."""
        recently_failed = self.episodic.recently_failed_issue_ids()
        candidates = self.github_client.list_candidate_issues(
            complexity_threshold=self.complexity_threshold
        )

        fresh: list[Issue] = []
        for issue in candidates:
            if self.in_progress.is_in_progress(issue.id):
                continue
            if issue.id in recently_failed:
                continue
            self.in_progress.mark(issue.id)
            fresh.append(issue)
        return fresh

    def run_forever(
        self,
        on_issue: Callable[[Issue], None],
        *,
        interval_minutes: int | None = None,
        max_cycles: int | None = None,
    ) -> None:
        """Continuous polling loop. `max_cycles` is for tests/demos so this
        doesn't run forever on camera; production use leaves it as None."""
        interval = interval_minutes if interval_minutes is not None else settings.poll_interval_minutes
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            for issue in self.poll_once():
                on_issue(issue)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            time.sleep(interval * 60)
