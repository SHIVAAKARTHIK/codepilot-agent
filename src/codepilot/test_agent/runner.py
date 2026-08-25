"""Deterministic test execution + result parsing.

This is the actual pass/fail signal the Coder's retry loop trusts - kept
separate from, and more reliable than, any LLM subagent's self-reported
summary. Retry-loop correctness shouldn't depend on a model grading its
own work.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT = 60

# pytest exit codes: 0 = all passed, 1 = tests failed, 2 = interrupted,
# 3 = internal error, 4 = usage error, 5 = no tests collected.
_EXIT_NO_TESTS_COLLECTED = 5

_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)")


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class, just named similarly

    passed: bool
    no_tests_collected: bool
    exit_code: int
    counts: dict[str, int] = field(default_factory=dict)
    failure_summary: list[str] = field(default_factory=list)
    raw_output: str = ""


def run_test_suite(sandbox_dir: Path, *, timeout: int = DEFAULT_TIMEOUT) -> TestResult:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", "--tb=short"],
            cwd=str(sandbox_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return TestResult(
            passed=False,
            no_tests_collected=False,
            exit_code=-1,
            raw_output=f"Test run timed out after {timeout}s: {exc}",
        )

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    counts = {m.group(2): int(m.group(1)) for m in _COUNT_RE.finditer(output)}

    return TestResult(
        passed=proc.returncode == 0,
        no_tests_collected=proc.returncode == _EXIT_NO_TESTS_COLLECTED,
        exit_code=proc.returncode,
        counts=counts,
        failure_summary=_extract_failure_lines(output),
        raw_output=output,
    )


def _extract_failure_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.startswith(("FAILED ", "ERROR "))]
