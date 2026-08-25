"""Text formatting for the PR Agent: branch names, commit messages, and PR
bodies - all structured per Component 6, not free-form LLM text.
"""
from __future__ import annotations

import re


def slugify(title: str, *, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug[:max_len].rstrip("-") or "task"


def branch_name(issue_number: int, issue_title: str) -> str:
    return f"codepilot/issue-{issue_number}-{slugify(issue_title)}"


def commit_message(*, issue_number: int, summary: str, what_changed: list[str], why: str) -> str:
    bullets = "\n".join(f"- {line}" for line in what_changed) or "- see diff"
    return f"fix(#{issue_number}): {summary}\n\n{bullets}\n- {why}\n- Closes #{issue_number}"


def pr_title(issue_title: str) -> str:
    return f"[CodePilot] {issue_title}"


def pr_body(
    *,
    issue_number: int,
    issue_url: str,
    approach: str,
    files_changed: list[str],
    test_summary: str,
) -> str:
    files_block = "\n".join(f"- `{f}`" for f in files_changed) or "(no files changed)"
    return (
        f"## Summary\n{approach}\n\n"
        f"## Files changed\n{files_block}\n\n"
        f"## Test results\n{test_summary}\n\n"
        f"## Issue\nCloses #{issue_number} - {issue_url}\n\n"
        "---\n*Opened automatically by CodePilot.*"
    )
