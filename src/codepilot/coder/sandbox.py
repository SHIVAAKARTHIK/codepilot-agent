"""Sandbox construction for the Coder agent: a fresh, isolated copy of only
the repo files the task actually needs - not the live repo, and per spec
not the full repository either.
"""
from __future__ import annotations

import shutil
from pathlib import Path


def create_sandbox(
    repo_root: Path, relevant_files: list[str], *, sandbox_base: Path, issue_id: str
) -> Path:
    sandbox_dir = Path(sandbox_base) / f"issue-{issue_id}"
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(repo_root).resolve()
    for rel_path in relevant_files:
        src = repo_root / rel_path
        if not src.is_file():
            continue
        dst = sandbox_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return sandbox_dir


def cleanup_sandbox(sandbox_dir: Path) -> None:
    if Path(sandbox_dir).exists():
        shutil.rmtree(sandbox_dir)
