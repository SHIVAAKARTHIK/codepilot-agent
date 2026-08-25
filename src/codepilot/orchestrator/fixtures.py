"""Hardcoded fake issue used for the Phase 1 "done when" check: prove the
Orchestrator can classify + plan without any live GitHub call."""
from __future__ import annotations

from src.codepilot.orchestrator.issue import Issue

FAKE_BUG_ISSUE = Issue(
    id="fake-1",
    number=1,
    title="Crash when the input list is empty",
    body=(
        "Calling `summarize(items)` with `items=[]` raises an unhandled "
        "IndexError instead of returning an empty summary. Expected: an "
        "empty list should return `{}` or a clear 'no items' result, not a "
        "crash."
    ),
    labels=["ai-assignable"],
)
