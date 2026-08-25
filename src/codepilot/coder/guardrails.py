"""Guardrail rule checks for the Coder agent (Component 3).

Deliberately plain, testable functions - no LLM, no framework dependency -
so the actual security-relevant logic can be unit tested directly, with the
framework glue (middleware.py) kept as thin as possible around it.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GuardrailViolation:
    kind: str  # "command" | "file_edit" | "hitl_gate"
    detail: str
    reason: str


_DANGEROUS_COMMAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcurl\b", re.IGNORECASE), "network fetch via curl"),
    (re.compile(r"\bwget\b", re.IGNORECASE), "network fetch via wget"),
    (re.compile(r"\bpip\s+install\b", re.IGNORECASE), "package install (network) via pip install"),
]

# Component 6's HITL gate table lists "any execute call containing git
# push" as requiring human approval (network operation) - distinct in kind
# from the hard "block" guardrails above, so it's tagged "hitl_gate" rather
# than "command". Behaviorally both currently refuse rather than proceed
# (see BUILD_PLAN.md on why true pause-and-resume needs Phase 8's TUI); the
# distinct kind is what lets that TUI tell "hard security block" apart
# from "needs a yes/no and could be approved."
_GIT_PUSH_RE = re.compile(r"\bgit\s+push\b", re.IGNORECASE)

# Flags can appear in either order (`-rf` or `-fr`, `sudo rm -r -f`, etc.),
# so this checks the flag cluster's letters rather than a fixed sequence.
_RM_RE = re.compile(r"\brm\s+(-[a-zA-Z]+)\b")


def _is_recursive_force_delete(command: str) -> bool:
    return any("r" in m.group(1).lower() and "f" in m.group(1).lower() for m in _RM_RE.finditer(command))

# Best-effort: find path-like tokens in a shell command string so we can
# flag ones that resolve outside the sandbox. This is a heuristic, not a
# full shell parser - matches the spec's own scope ("any command targeting
# paths outside /sandbox/"), not a claim of airtight shell-injection safety.
_PATH_TOKEN_RE = re.compile(r"(?:[A-Za-z]:\\[^\s\"'|&;]+|/[^\s\"'|&;]+)")

_FORBIDDEN_FILENAME_GLOBS = ["*.env", "*.secret", "*.pem", "*.key", "*credentials*"]


def check_execute_command(command: str, *, sandbox_root: str | Path) -> GuardrailViolation | None:
    """Block dangerous commands and commands that reference a path outside
    the sandbox. Returns None if the command is fine."""
    if _is_recursive_force_delete(command):
        return GuardrailViolation(
            kind="command", detail=command, reason="blocked pattern: recursive force-delete (rm -rf or a flag-order variant)"
        )

    if _GIT_PUSH_RE.search(command):
        return GuardrailViolation(
            kind="hitl_gate", detail=command, reason="git push is a network operation and requires human approval"
        )

    for pattern, reason in _DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(command):
            return GuardrailViolation(kind="command", detail=command, reason=f"blocked pattern: {reason}")

    sandbox_root_resolved = str(Path(sandbox_root).resolve())
    for token in _PATH_TOKEN_RE.findall(command):
        candidate = token.rstrip(").,;")
        try:
            resolved = str(Path(candidate).resolve())
        except (OSError, ValueError):
            continue
        if not resolved.startswith(sandbox_root_resolved):
            return GuardrailViolation(
                kind="command",
                detail=command,
                reason=f"command references a path outside the sandbox: {candidate}",
            )
    return None


def check_file_edit(file_path: str) -> GuardrailViolation | None:
    """Block writes/edits to secret- or credential-shaped filenames.
    Returns None if the edit is fine."""
    name = Path(file_path).name.lower()
    for pattern in _FORBIDDEN_FILENAME_GLOBS:
        if fnmatch.fnmatch(name, pattern):
            return GuardrailViolation(
                kind="file_edit", detail=file_path, reason=f"forbidden file pattern: {pattern}"
            )
    return None
