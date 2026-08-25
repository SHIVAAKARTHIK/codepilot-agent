"""Active Task panel: current issue, pipeline state, skill, and todo
checklist for whichever issue is currently being worked.
"""
from __future__ import annotations

from textual.widgets import Static

_TODO_SYMBOLS = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}


class ActiveTaskPanel(Static):
    BORDER_TITLE = "Active Task"

    def on_mount(self) -> None:
        self.show_idle()

    def show_idle(self) -> None:
        self.update("(no active task)")

    def show_task(
        self,
        *,
        issue_number: int,
        issue_title: str,
        state: str,
        skill_name: str | None = None,
        retries: int = 0,
        todos: list[dict] | None = None,
    ) -> None:
        lines = [f"Issue #{issue_number}: {issue_title}", f"Status: {state}"]
        if skill_name:
            lines.append(f"Skill: {skill_name}")
        if retries:
            lines.append(f"Retries: {retries}")
        if todos:
            lines.append("Todo:")
            for todo in todos:
                symbol = _TODO_SYMBOLS.get(todo.get("status"), "[ ]")
                lines.append(f"  {symbol} {todo.get('content', '')}")
        self.update("\n".join(lines))
