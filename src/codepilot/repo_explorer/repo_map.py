"""Repo Map: a compressed, queryable representation of a repository
(Component 2's core artifact).

Deliberately built via static analysis rather than an LLM: parsing
top-level symbols (`ast` for Python, regex for JS/TS) and deriving a
1-line description from each file's docstring/leading comment costs zero
tokens and rebuilds in well under a second even for a few hundred files.
Real repo-map tools (e.g. aider) take the same approach for the same
reason. The Repo Explorer stays purely deterministic; only the subagents
that *use* this map to decide what to `read_file` (Coder, from Phase 4)
involve the LLM.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_EXCLUDE_DIRS = {
    "__pycache__", "node_modules", "venv", "env", "dist", "build",
    "site-packages", "egg-info",
}

_LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".rs": "rust",
    ".md": "markdown",
}

# Rough local approximation (no tokenizer dependency) used only to enforce
# the map's own token budget - good enough for a stop-adding-files cutoff.
_CHARS_PER_TOKEN = 4


@dataclass
class FileSummary:
    path: str  # POSIX-style, relative to repo root
    language: str
    exported_symbols: list[str] = field(default_factory=list)
    description: str = "(no description)"

    def render(self) -> str:
        symbols = ", ".join(self.exported_symbols) if self.exported_symbols else "-"
        return f"- `{self.path}` [{self.language}] {self.description} | symbols: {symbols}"


@dataclass
class RepoMap:
    repo_root: str
    fingerprint: str
    generated_at: str
    token_budget: int
    files: list[FileSummary] = field(default_factory=list)
    truncated: bool = False
    omitted_count: int = 0

    def to_text(self) -> str:
        header = (
            "# Repo Map\n"
            f"repo: {self.repo_root}\n"
            f"generated: {self.generated_at}\n"
            f"files: {len(self.files)}"
        )
        if self.truncated:
            header += f" (truncated, {self.omitted_count} omitted to fit {self.token_budget}-token budget)"
        header += "\n\n"

        by_dir: dict[str, list[FileSummary]] = {}
        for f in self.files:
            d = str(Path(f.path).parent).replace("\\", "/")
            by_dir.setdefault(d, []).append(f)

        body_lines: list[str] = []
        for d in sorted(by_dir):
            body_lines.append(f"## {d}/" if d != "." else "## (root)")
            for f in sorted(by_dir[d], key=lambda x: x.path):
                body_lines.append(f.render())
            body_lines.append("")
        return header + "\n".join(body_lines)

    def token_estimate(self) -> int:
        return len(self.to_text()) // _CHARS_PER_TOKEN


def _walk_repo(repo_root: Path) -> list[Path]:
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS and not d.startswith(".")]
        for name in filenames:
            if Path(name).suffix in _LANGUAGE_BY_EXT:
                results.append(Path(dirpath) / name)
    return results


def _extract_python_symbols(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


_JS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"
    r"|^\s*(?:export\s+)?class\s+(\w+)"
    r"|^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:\([^)]*\)\s*=>|function)",
    re.MULTILINE,
)


def _extract_js_symbols(source: str) -> list[str]:
    symbols = []
    for match in _JS_SYMBOL_RE.finditer(source):
        name = next((g for g in match.groups() if g), None)
        if name:
            symbols.append(name)
    return symbols


def _extract_description(source: str, language: str) -> str:
    if language == "python":
        try:
            doc = ast.get_docstring(ast.parse(source))
        except SyntaxError:
            doc = None
        if doc:
            return doc.strip().splitlines()[0][:160]
    for line in source.splitlines()[:20]:
        stripped = line.strip().lstrip("#/*->").strip()
        if stripped:
            return stripped[:160]
    return "(no description)"


def _summarize_file(path: Path, repo_root: Path) -> FileSummary | None:
    language = _LANGUAGE_BY_EXT.get(path.suffix, "text")
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    if language == "python":
        symbols = _extract_python_symbols(source)
    elif language in ("javascript", "typescript"):
        symbols = _extract_js_symbols(source)
    else:
        symbols = []

    return FileSummary(
        path=path.relative_to(repo_root).as_posix(),
        language=language,
        exported_symbols=symbols,
        description=_extract_description(source, language),
    )


def _repo_fingerprint(repo_root: Path) -> str:
    """HEAD commit + any uncommitted changes, hashed. Generalizes the
    spec's "use git diff to detect changes since last run" to also catch
    uncommitted edits, not just new commits."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout
        raw = f"{head}\n{dirty}"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        raw = _fallback_fingerprint(repo_root)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _fallback_fingerprint(repo_root: Path) -> str:
    """Not a git repo (or git unavailable): fingerprint by mtime+size so
    caching still invalidates on change."""
    parts = []
    for path in _walk_repo(repo_root):
        try:
            stat = path.stat()
        except OSError:
            continue
        parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    return "\n".join(sorted(parts))


def build_repo_map(repo_root: Path, *, token_budget: int) -> RepoMap:
    repo_root = Path(repo_root).resolve()
    all_summaries = [
        s for s in (_summarize_file(p, repo_root) for p in sorted(_walk_repo(repo_root))) if s is not None
    ]

    repo_map = RepoMap(
        repo_root=str(repo_root),
        fingerprint=_repo_fingerprint(repo_root),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        token_budget=token_budget,
        files=[],
    )

    included: list[FileSummary] = []
    for summary in all_summaries:
        repo_map.files = included + [summary]
        if repo_map.token_estimate() > token_budget and included:
            repo_map.files = included
            repo_map.truncated = True
            repo_map.omitted_count = len(all_summaries) - len(included)
            return repo_map
        included = repo_map.files

    repo_map.files = included
    return repo_map


def _cache_path(repo_root: Path, cache_dir: Path) -> Path:
    slug = hashlib.sha256(str(repo_root).encode()).hexdigest()[:16]
    return cache_dir / f"{slug}.json"


def save_repo_map(repo_map: RepoMap, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(Path(repo_map.repo_root), cache_dir)
    path.write_text(json.dumps(asdict(repo_map), indent=2), encoding="utf-8")
    return path


def load_repo_map(repo_root: Path, cache_dir: Path) -> RepoMap | None:
    path = _cache_path(Path(repo_root).resolve(), cache_dir)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["files"] = [FileSummary(**f) for f in data["files"]]
    return RepoMap(**data)


def build_or_load_repo_map(repo_root: Path, *, cache_dir: Path, token_budget: int) -> tuple[RepoMap, bool]:
    """Returns `(repo_map, was_cached)`. Rebuilds only when the repo's
    fingerprint or the configured token budget has changed since the last
    cached build."""
    repo_root = Path(repo_root).resolve()
    current_fingerprint = _repo_fingerprint(repo_root)
    cached = load_repo_map(repo_root, cache_dir)
    if cached is not None and cached.fingerprint == current_fingerprint and cached.token_budget == token_budget:
        return cached, True
    fresh = build_repo_map(repo_root, token_budget=token_budget)
    save_repo_map(fresh, cache_dir)
    return fresh, False
