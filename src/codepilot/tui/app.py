"""CodePilot's Textual UI (Component 7): the 4-panel layout from spec.

┌──────────────────┬──────────────────────────────┐
│  GitHub Issues   │        Active Task            │
├──────────────────┼──────────────────────────────┤
│   Agent Logs     │       Human Approval          │
└──────────────────┴──────────────────────────────┘
  [i] New task  [s] Skip issue  [q] Quit  [l] Logs

Architecture: two background workers (`@work(thread=True)`) - a poll loop
that discovers issues and a task processor that pulls them off a queue one
at a time and drives `run_full_pipeline_for_issue`. Both run on worker
threads so the UI's asyncio event loop is never blocked by an LLM call.

The Human Approval flow is a genuine pause-and-resume, not a fake one: the
task-processor thread blocks on a `threading.Event` inside
`_handle_approval_needed` until the *main UI thread* sets it in response to
a real keypress (`action_approve` / `action_reject`) - the UI stays fully
responsive throughout since only the background worker is waiting.
"""
from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label

from src.codepilot.github_client import GitHubClient
from src.codepilot.memory.episodic import EpisodicMemory
from src.codepilot.memory.semantic import SemanticMemory
from src.codepilot.orchestrator.in_progress import InProgressTracker
from src.codepilot.orchestrator.issue import Issue
from src.codepilot.orchestrator.pipeline import ApprovalDecision, PipelineResult, run_full_pipeline_for_issue
from src.codepilot.pr_agent.gates import PendingApproval
from src.codepilot.repo_explorer.explorer import RepoExplorer
from src.codepilot.tui.panels.active_task import ActiveTaskPanel
from src.codepilot.tui.panels.agent_logs import AgentLogsPanel
from src.codepilot.tui.panels.human_approval import HumanApprovalPanel
from src.codepilot.tui.panels.issues import IssuesPanel

_APP_CSS = """
Screen {
    layout: grid;
    grid-size: 2 2;
    grid-rows: 1fr 1fr;
    grid-columns: 1fr 1fr;
}
IssuesPanel, ActiveTaskPanel, AgentLogsPanel, HumanApprovalPanel {
    border: round $accent;
    border-title-align: left;
    height: 100%;
}
#new-task-dialog {
    align: center middle;
    width: 60%;
    height: auto;
    border: round $accent;
    padding: 1 2;
    background: $panel;
}
"""


class NewTaskScreen(ModalScreen[str | None]):
    """`[i] New task`: free-form input, not tied to a GitHub issue."""

    def compose(self) -> ComposeResult:
        with Container(id="new-task-dialog"):
            yield Label("Describe the task (Enter to submit, Esc to cancel):")
            yield Input(placeholder="e.g. Add a --verbose flag to the CLI", id="new-task-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class CodePilotApp(App):
    CSS = _APP_CSS
    TITLE = "CodePilot"
    BINDINGS = [
        ("i", "new_task", "New task"),
        ("s", "skip_issue", "Skip issue"),
        ("q", "quit", "Quit"),
        ("l", "toggle_logs", "Logs"),
        ("a", "approve", "Approve"),
        ("r", "reject", "Reject"),
        ("x", "inspect", "Inspect"),
    ]

    def __init__(
        self,
        *,
        repo_root: Path,
        repo_explorer: RepoExplorer,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
        github_client: GitHubClient | None,
        repo_id: str,
        issue_source: Any,
        poll_interval_minutes: int = 5,
    ) -> None:
        super().__init__()
        self.repo_root = repo_root
        self.repo_explorer = repo_explorer
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory
        self.github_client = github_client
        self.repo_id = repo_id
        self.issue_source = issue_source
        self.poll_interval_minutes = poll_interval_minutes

        self._in_progress = InProgressTracker()
        self._queue_lock = threading.Lock()
        self._queue: deque[Issue] = deque()
        self._queued_ids: set[str] = set()
        self._new_item_event = threading.Event()
        self._stop_event = threading.Event()

        self._approval_event = threading.Event()
        self._approval_decision: ApprovalDecision | None = None
        self._pending_gates: list[PendingApproval] = []

        self._local_task_counter = 0
        self._active_issue: Issue | None = None

    # --- layout ---
    def compose(self) -> ComposeResult:
        yield Header()
        yield IssuesPanel(id="issues")
        yield ActiveTaskPanel(id="active-task")
        yield AgentLogsPanel(id="agent-logs")
        yield HumanApprovalPanel(id="human-approval")
        yield Footer()

    def on_mount(self) -> None:
        self.run_poll_loop()
        self.run_task_processor()

    def on_unmount(self) -> None:
        self._stop_event.set()
        self._new_item_event.set()
        self._approval_event.set()  # never leave a worker stuck waiting on shutdown

    # --- background workers ---
    @work(thread=True, exclusive=True, group="poll")
    def run_poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                issues = self.issue_source.poll_once()
            except Exception as exc:  # noqa: BLE001 - surface, don't crash the worker
                self.call_from_thread(self._log, f"[poll] error: {exc}")
                issues = []
            for issue in issues:
                self._enqueue(issue)
            if self._stop_event.wait(timeout=max(self.poll_interval_minutes, 1) * 60):
                break

    @work(thread=True, exclusive=True, group="process")
    def run_task_processor(self) -> None:
        while not self._stop_event.is_set():
            issue = self._dequeue()
            if issue is None:
                self._new_item_event.wait(timeout=1)
                continue
            self._in_progress.mark(issue.id)
            self._run_pipeline_for_issue(issue)
            self._in_progress.unmark(issue.id)

    # --- queue management (thread-safe; called from either worker thread) ---
    def _enqueue(self, issue: Issue) -> None:
        with self._queue_lock:
            if issue.id in self._queued_ids or self._in_progress.is_in_progress(issue.id):
                return
            self._queue.append(issue)
            self._queued_ids.add(issue.id)
        self._new_item_event.set()
        self.call_from_thread(self._on_issue_queued, issue)

    def _dequeue(self) -> Issue | None:
        with self._queue_lock:
            if not self._queue:
                self._new_item_event.clear()
                return None
            issue = self._queue.popleft()
            self._queued_ids.discard(issue.id)
            return issue

    # --- pipeline execution (runs on the "process" worker thread) ---
    def _run_pipeline_for_issue(self, issue: Issue) -> None:
        self.call_from_thread(self._on_issue_started, issue)

        def on_progress(stage: str, message: str) -> None:
            self.call_from_thread(self._log, f"[{stage}] {message}")
            self.call_from_thread(self._update_active_task, issue, stage)

        result = run_full_pipeline_for_issue(
            issue,
            repo_root=self.repo_root,
            repo_explorer=self.repo_explorer,
            episodic_memory=self.episodic_memory,
            semantic_memory=self.semantic_memory,
            github_client=self.github_client,
            repo_id=self.repo_id,
            on_progress=on_progress,
            on_approval_needed=self._handle_approval_needed,
        )

        self.call_from_thread(self._on_issue_finished, issue, result)

    def _handle_approval_needed(self, pending: list[PendingApproval]) -> ApprovalDecision:
        """Blocks the calling (task-processor) worker thread until a human
        presses (a)pprove or (r)eject in the main UI thread."""
        self._pending_gates = pending
        self._approval_event.clear()
        self.call_from_thread(self.query_one(HumanApprovalPanel).show_pending, pending)
        self.call_from_thread(self._log, f"[APPROVAL] waiting for a human decision on {len(pending)} gate(s)")
        self._approval_event.wait()
        decision = self._approval_decision or ApprovalDecision(approved=False)
        self._approval_decision = None
        return decision

    # --- UI-thread-only update methods (always called via call_from_thread from workers) ---
    def _log(self, text: str) -> None:
        self.query_one(AgentLogsPanel).log_line(text)

    def _on_issue_queued(self, issue: Issue) -> None:
        self.query_one(IssuesPanel).upsert(
            issue_id=issue.id, number=issue.number, title=issue.title, status="queued"
        )
        self._log(f"Queued issue #{issue.number}: {issue.title}")

    def _on_issue_started(self, issue: Issue) -> None:
        self._active_issue = issue
        self.query_one(IssuesPanel).upsert(
            issue_id=issue.id, number=issue.number, title=issue.title, status="in-progress"
        )
        self.query_one(ActiveTaskPanel).show_task(issue_number=issue.number, issue_title=issue.title, state="TRIAGED")

    def _update_active_task(self, issue: Issue, stage: str) -> None:
        if self._active_issue is not issue:
            return
        self.query_one(ActiveTaskPanel).show_task(issue_number=issue.number, issue_title=issue.title, state=stage)
        if stage == "APPROVAL":
            self.query_one(IssuesPanel).upsert(
                issue_id=issue.id, number=issue.number, title=issue.title, status="pending-approval"
            )

    def _on_issue_finished(self, issue: Issue, result: PipelineResult) -> None:
        status = "done" if result.state_machine.state.value == "DONE" else "failed"
        self.query_one(IssuesPanel).upsert(issue_id=issue.id, number=issue.number, title=issue.title, status=status)
        todos = result.coder_result.todos if result.coder_result else []
        self.query_one(ActiveTaskPanel).show_task(
            issue_number=issue.number,
            issue_title=issue.title,
            state=result.state_machine.state.value,
            retries=result.coder_result.retries if result.coder_result else 0,
            todos=todos,
        )
        if status == "done" and result.pr_result and result.pr_result.pr_url:
            self._log(f"[DONE] {result.pr_result.pr_url}")
        elif result.error:
            self._log(f"[FAILED] {result.error}")
        if self._active_issue is issue:
            self._active_issue = None

    # --- key bindings / actions ---
    def action_approve(self) -> None:
        if not self._pending_gates:
            return
        gates = frozenset(g.gate for g in self._pending_gates)
        self._pending_gates = []
        self.query_one(HumanApprovalPanel).show_resolved(approved=True)
        self._approval_decision = ApprovalDecision(approved=True, approved_gates=gates)
        self._approval_event.set()

    def action_reject(self) -> None:
        if not self._pending_gates:
            return
        self._pending_gates = []
        self.query_one(HumanApprovalPanel).show_resolved(approved=False)
        self._approval_decision = ApprovalDecision(approved=False)
        self._approval_event.set()

    def action_inspect(self) -> None:
        panel = self.query_one(HumanApprovalPanel)
        if not self._pending_gates:
            self._log("[inspect] no pending approvals")
            return
        for gate in self._pending_gates:
            panel.show_guardrail_violation(kind=gate.gate, reason=gate.reason, detail=gate.detail)

    def action_skip_issue(self) -> None:
        with self._queue_lock:
            if not self._queue:
                self._log("[skip] queue is empty")
                return
            issue = self._queue.popleft()
            self._queued_ids.discard(issue.id)
        self.query_one(IssuesPanel).upsert(
            issue_id=issue.id, number=issue.number, title=issue.title, status="skipped"
        )
        self._log(f"[skip] Skipped issue #{issue.number}: {issue.title}")

    def action_toggle_logs(self) -> None:
        panel = self.query_one(AgentLogsPanel)
        panel.display = not panel.display

    def action_new_task(self) -> None:
        def handle_result(text: str | None) -> None:
            if not text:
                return
            self._local_task_counter += 1
            issue = Issue(
                id=f"local-{self._local_task_counter}",
                number=0,
                title=text.splitlines()[0][:80],
                body=text,
                reporter=None,
            )
            self._enqueue(issue)

        self.push_screen(NewTaskScreen(), handle_result)
