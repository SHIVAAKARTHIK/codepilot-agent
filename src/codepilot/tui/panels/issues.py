"""Issues panel: DataTable listing known issues and their status. Updates
live as the poll loop discovers issues and the task processor works
through them.
"""
from __future__ import annotations

from textual.widgets import DataTable

_STATUS_SYMBOLS = {
    "queued": "○",  # (open circle)
    "in-progress": "◐",  # (half circle)
    "pending-approval": "⚠",  # (warning)
    "done": "●",  # (filled circle)
    "failed": "✗",  # (cross)
    "skipped": "⊖",  # (circled minus)
}


class IssuesPanel(DataTable):
    BORDER_TITLE = "GitHub Issues"

    def on_mount(self) -> None:
        self.add_columns(("#", "number"), ("Title", "title"), ("Status", "status"))
        self.cursor_type = "row"
        self._known: set[str] = set()

    def upsert(self, *, issue_id: str, number: int, title: str, status: str) -> None:
        symbol = _STATUS_SYMBOLS.get(status, "?")
        label = f"{symbol} {status}"
        if issue_id in self._known:
            self.update_cell(issue_id, "status", label)
        else:
            self.add_row(str(number), title, label, key=issue_id)
            self._known.add(issue_id)
