"""RepoExplorer: facade over Repo Map construction/caching and the two
retrieval strategies (Component 2). Fully deterministic - no LLM calls -
so "what files are relevant to this task" resolves in milliseconds.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from deepagents.backends.utils import create_file_data

from src.codepilot.config import settings
from src.codepilot.repo_explorer.repo_map import RepoMap, build_or_load_repo_map
from src.codepilot.repo_explorer.retrieval import (
    ScoredFile,
    embedding_search,
    index_files_for_embedding_search,
    keyword_search,
)

REPO_MAP_VIRTUAL_PATH = "/repo_map.md"


class RepoExplorer:
    def __init__(
        self,
        repo_root: Path,
        *,
        token_budget: int | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.token_budget = token_budget or settings.repo_map_token_budget
        self.cache_dir = cache_dir or (settings.project_root / ".repo_map_cache")
        self.repo_map: RepoMap | None = None
        self.was_cached: bool = False
        self._embedding_indexed = False

    def build_or_load(self) -> RepoMap:
        self.repo_map, self.was_cached = build_or_load_repo_map(
            self.repo_root, cache_dir=self.cache_dir, token_budget=self.token_budget
        )
        return self.repo_map

    def select_relevant_files(
        self, query: str, *, top_k: int | None = None, strategy: str = "auto"
    ) -> list[ScoredFile]:
        """`strategy`: "keyword" (fast), "embedding" (slower, semantic), or
        "auto" - keyword first, falling back to embedding search only if
        keyword matching finds nothing (the Orchestrator's default choice)."""
        if self.repo_map is None:
            self.build_or_load()
        top_k = top_k or settings.retrieval_top_k

        if strategy in ("keyword", "auto"):
            results = keyword_search(self.repo_map, query, top_k=top_k)
            if results or strategy == "keyword":
                return results

        self._ensure_embedding_index()
        return embedding_search(query, persist_dir=self._embedding_dir, top_k=top_k)

    def virtual_fs_files(self) -> dict[str, dict]:
        """The Repo Map, ready to merge into a deep agent's initial `files`
        state so every subagent can `read_file("/repo_map.md")` without
        rebuilding it (spec: store it in the deepagents virtual filesystem
        via `write_file`)."""
        if self.repo_map is None:
            self.build_or_load()
        return {REPO_MAP_VIRTUAL_PATH: create_file_data(self.repo_map.to_text())}

    def _ensure_embedding_index(self) -> None:
        if self._embedding_indexed:
            return
        index_files_for_embedding_search(self.repo_root, self.repo_map.files, persist_dir=self._embedding_dir)
        self._embedding_indexed = True

    @property
    def _embedding_dir(self) -> Path:
        slug = hashlib.sha256(str(self.repo_root).encode()).hexdigest()[:16]
        return settings.chroma_persist_dir / slug
