"""Semantic memory (cross-session, persistent): after each successfully
merged PR, extract a "lesson learned" and store it in a searchable vector
store, keyed by repository + issue type (Component 5).

Before starting a new task, the Orchestrator retrieves the top-3 most
similar past lessons for the same repo + task type and injects them into
the Coder's context.

Uses ChromaDB with its bundled local embedding model (the same
`all-MiniLM-L6-v2` onnxruntime model already used for Repo Explorer's
embedding retrieval in Phase 3) - no external embeddings API/key needed,
and the model is already cached locally by that point in most setups.

"Keyed by repository + issue type" is implemented as metadata filtering
(`where={"$and": [{"repo": ...}, {"task_type": ...}]}`) rather than one
physical Chroma collection per repo/type pair, which would fragment the
index for no benefit - a single collection with a metadata filter is the
idiomatic way to scope a vector search like this.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.codepilot.config import settings

_COLLECTION_NAME = "codepilot_lessons"


@dataclass
class Lesson:
    lesson_id: str
    repo: str
    task_type: str
    issue_summary: str
    approach: str
    files_changed: list[str] = field(default_factory=list)
    created_at: str = ""


class SemanticMemory:
    def __init__(self, persist_dir: Path | None = None) -> None:
        self.persist_dir = Path(persist_dir) if persist_dir else settings.chroma_persist_dir
        self._collection = None

    def _ensure_collection(self):
        if self._collection is None:
            import chromadb

            client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = client.get_or_create_collection(_COLLECTION_NAME)
        return self._collection

    def record_lesson(
        self, *, repo: str, task_type: str, issue_summary: str, approach: str, files_changed: list[str]
    ) -> Lesson:
        """Spec: "After each successfully merged PR, extract a 'lesson
        learned' entry: what the issue was, what files were changed, what
        approach worked." Called once a PR opens successfully."""
        collection = self._ensure_collection()
        lesson = Lesson(
            lesson_id=uuid.uuid4().hex,
            repo=repo,
            task_type=task_type,
            issue_summary=issue_summary,
            approach=approach,
            files_changed=list(files_changed),
            created_at=_now(),
        )
        collection.add(
            ids=[lesson.lesson_id],
            documents=[f"{issue_summary}\n\nApproach: {approach}"],
            metadatas=[
                {
                    "repo": repo,
                    "task_type": task_type,
                    "issue_summary": issue_summary,
                    "approach": approach,
                    "files_changed": json.dumps(list(files_changed)),
                    "created_at": lesson.created_at,
                }
            ],
        )
        return lesson

    def retrieve_similar_lessons(self, *, repo: str, task_type: str, query: str, top_k: int = 3) -> list[Lesson]:
        """Spec: "the Orchestrator retrieves the top-3 most similar past
        lessons and injects them into the Coder agent's context"."""
        collection = self._ensure_collection()
        if collection.count() == 0:
            return []

        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where={"$and": [{"repo": repo}, {"task_type": task_type}]},
        )
        if not results["ids"] or not results["ids"][0]:
            return []

        lessons = []
        for lesson_id, meta in zip(results["ids"][0], results["metadatas"][0]):
            lessons.append(
                Lesson(
                    lesson_id=lesson_id,
                    repo=meta["repo"],
                    task_type=meta["task_type"],
                    issue_summary=meta["issue_summary"],
                    approach=meta["approach"],
                    files_changed=json.loads(meta.get("files_changed", "[]")),
                    created_at=meta.get("created_at", ""),
                )
            )
        return lessons


def lessons_to_prompt_block(lessons: list[Lesson]) -> str:
    """Rendered for injection into the Coder's task prompt, alongside the
    Skill block (see coder/agent.py)."""
    if not lessons:
        return ""
    lines = ["## Lessons from similar past issues in this repo"]
    for lesson in lessons:
        files = ", ".join(lesson.files_changed) or "(none recorded)"
        lines.append(f"- Issue: {lesson.issue_summary}\n  Approach that worked: {lesson.approach}\n  Files touched: {files}")
    return "\n".join(lines) + "\n"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
