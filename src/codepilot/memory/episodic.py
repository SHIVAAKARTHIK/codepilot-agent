"""Episodic memory (session-scoped): all reads/writes go through LangGraph's
Store API (`put` / `search`), per the spec.

Note: this environment only ships `langgraph.store.memory.InMemoryStore` -
no sqlite/postgres store backend is installed - and `InMemoryStore` does not
survive a process restart on its own. Since the spec's actual required
behavior ("the Orchestrator reads the last 3 session summaries at startup")
only means something *across restarts*, this class mirrors every write to a
small JSON file next to the store and replays it on construction. All real
read/write access still goes through the LangGraph Store API; the JSON file
is purely a persistence shim for `InMemoryStore`'s gap, not a second source
of truth.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.store.memory import InMemoryStore

from src.codepilot.config import settings

_NAMESPACE = ("codepilot", "episodic_sessions")


@dataclass
class TaskLogEntry:
    issue_id: str
    task_type: str
    files_modified: list[str]
    outcome: str  # "DONE" | "FAILED" | any TaskState value while a run is in-flight
    duration_seconds: float


@dataclass
class SessionSummary:
    session_id: str
    started_at: str
    ended_at: str
    tasks: list[TaskLogEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "tasks": [vars(t) for t in self.tasks],
        }


class EpisodicMemory:
    """One instance per running CodePilot session."""

    def __init__(self, persist_path: Path | None = None) -> None:
        self.session_id = uuid.uuid4().hex[:8]
        self.started_at = _now()
        self._tasks: list[TaskLogEntry] = []

        self._persist_path = persist_path or (settings.project_root / ".codepilot_episodic.json")
        self.store = InMemoryStore()
        self._load_persisted()

    def log_task(self, entry: TaskLogEntry) -> None:
        self._tasks.append(entry)

    def end_session(self) -> SessionSummary:
        """Write a structured session summary to the store (spec: "At
        session end, write a structured session summary to the memory
        store")."""
        summary = SessionSummary(
            session_id=self.session_id,
            started_at=self.started_at,
            ended_at=_now(),
            tasks=list(self._tasks),
        )
        self.store.put(_NAMESPACE, summary.session_id, summary.to_dict())
        self._persist_to_disk()
        return summary

    def recent_session_summaries(self, limit: int = 3) -> list[dict[str, Any]]:
        """Spec: "The Orchestrator reads the last 3 session summaries at
        startup"."""
        items = self.store.search(_NAMESPACE, limit=100)
        items.sort(key=lambda item: item.value.get("ended_at", ""), reverse=True)
        return [item.value for item in items[:limit]]

    def recently_failed_issue_ids(self, limit_sessions: int = 3) -> set[str]:
        """Spec: "...to avoid retrying recently failed issues" - the
        IssuePoller checks this before handing an issue to the Orchestrator."""
        failed: set[str] = set()
        for session in self.recent_session_summaries(limit=limit_sessions):
            for task in session.get("tasks", []):
                if task.get("outcome") == "FAILED":
                    failed.add(task["issue_id"])
        return failed

    # --- persistence shim for InMemoryStore ---
    def _persist_to_disk(self) -> None:
        items = self.store.search(_NAMESPACE, limit=1000)
        payload = {item.key: item.value for item in items}
        self._persist_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_persisted(self) -> None:
        if not self._persist_path.exists():
            return
        payload = json.loads(self._persist_path.read_text(encoding="utf-8"))
        for key, value in payload.items():
            self.store.put(_NAMESPACE, key, value)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
