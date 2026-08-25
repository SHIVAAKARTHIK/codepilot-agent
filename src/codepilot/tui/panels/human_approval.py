"""Human Approval panel: surfaces HITL pending-approval gates and
guardrail violations; waits for approve/reject/inspect keyboard input
(handled by the App - this widget just renders state).
"""
from __future__ import annotations

from textual.widgets import RichLog

from src.codepilot.pr_agent.gates import PendingApproval


class HumanApprovalPanel(RichLog):
    BORDER_TITLE = "Human Approval"

    def on_mount(self) -> None:
        self.markup = True
        self.write("(no pending approvals)")

    def show_pending(self, pending: list[PendingApproval]) -> None:
        self.clear()
        self.write("[bold yellow]Approval needed[/bold yellow] - (a) approve  (r) reject  (x) inspect")
        for p in pending:
            self.write(f"  ⚠ [b]{p.gate}[/b]: {p.reason} ({p.detail})")

    def show_resolved(self, *, approved: bool) -> None:
        label = "[bold green]APPROVED[/bold green]" if approved else "[bold red]REJECTED[/bold red]"
        self.write(f"  -> {label}")

    def show_guardrail_violation(self, *, kind: str, reason: str, detail: str) -> None:
        self.write(f"[dim]guardrail[/dim] [{kind}] {reason} ({detail})")
