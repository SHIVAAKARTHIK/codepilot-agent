"""Agent Logs panel: streams pipeline/agent progress as it happens
(spec: "streams agent thoughts and tool calls as they happen").
"""
from __future__ import annotations

from datetime import datetime

from textual.widgets import RichLog


class AgentLogsPanel(RichLog):
    BORDER_TITLE = "Agent Logs"

    def on_mount(self) -> None:
        self.wrap = True
        self.markup = True

    def log_line(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.write(f"[dim]{timestamp}[/dim] {text}")
