"""Minimal issue representation shared by the Orchestrator now and the real
GitHub polling loop from Phase 2 onward. Deliberately provider-agnostic so
Phase 1 can be tested without any GitHub call.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Issue:
    id: str
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
