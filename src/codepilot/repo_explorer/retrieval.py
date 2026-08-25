"""Two relevant-file retrieval strategies over a `RepoMap`, per Component 2.
The Orchestrator/RepoExplorer picks between them (see explorer.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.codepilot.repo_explorer.repo_map import FileSummary, RepoMap

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")

_CHUNK_COLLECTION = "codepilot_file_chunks"


@dataclass
class ScoredFile:
    path: str
    score: float
    reason: str  # "keyword" | "embedding"


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 2}


def keyword_search(repo_map: RepoMap, query: str, *, top_k: int = 10) -> list[ScoredFile]:
    """Fast path: score files by overlap between the query's words and
    each file's path/description/exported-symbol words. Symbol matches
    weigh more (a query mentioning a function name is a strong signal)."""
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    scored: list[ScoredFile] = []
    for f in repo_map.files:
        symbol_terms = {s.lower() for s in f.exported_symbols}
        text_terms = _tokenize(f.path) | _tokenize(f.description)

        score = 0.0
        for term in query_terms:
            if term in symbol_terms:
                score += 2.0
            elif term in text_terms:
                score += 1.0
        if score > 0:
            scored.append(ScoredFile(path=f.path, score=score, reason="keyword"))

    scored.sort(key=lambda sf: sf.score, reverse=True)
    return scored[:top_k]


def _chunk_text(text: str, chunk_chars: int, overlap: int) -> list[str]:
    if len(text) <= chunk_chars:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    step = max(chunk_chars - overlap, 1)
    while start < len(text):
        chunks.append(text[start : start + chunk_chars])
        start += step
    return chunks


def index_files_for_embedding_search(
    repo_root: Path,
    files: list[FileSummary],
    *,
    persist_dir: Path,
    chunk_chars: int = 1200,
    chunk_overlap: int = 200,
) -> int:
    """Chunk file contents and (re)build a ChromaDB collection. Uses
    Chroma's bundled local embedding model (onnxruntime-based) - no
    external embeddings API or key needed. Returns the number of chunks
    indexed."""
    import chromadb

    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        client.delete_collection(_CHUNK_COLLECTION)
    except Exception:
        pass
    collection = client.create_collection(_CHUNK_COLLECTION)

    ids, docs, metadatas = [], [], []
    for f in files:
        try:
            text = (repo_root / f.path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for idx, chunk in enumerate(_chunk_text(text, chunk_chars, chunk_overlap)):
            ids.append(f"{f.path}::chunk{idx}")
            docs.append(chunk)
            metadatas.append({"path": f.path, "language": f.language})

    if not docs:
        return 0
    collection.add(ids=ids, documents=docs, metadatas=metadatas)
    return len(docs)


def embedding_search(query: str, *, persist_dir: Path, top_k: int = 10) -> list[ScoredFile]:
    """Slow(er) path: semantic similarity over indexed file-content chunks.
    Requires `index_files_for_embedding_search` to have run first for this
    `persist_dir`; returns [] if no index exists yet."""
    import chromadb

    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        collection = client.get_collection(_CHUNK_COLLECTION)
    except Exception:
        return []

    results = collection.query(query_texts=[query], n_results=max(top_k * 3, top_k))
    if not results["ids"] or not results["ids"][0]:
        return []

    best_score_by_path: dict[str, float] = {}
    for meta, distance in zip(results["metadatas"][0], results["distances"][0]):
        path = meta["path"]
        similarity = 1.0 / (1.0 + distance)  # smaller distance = more similar
        best_score_by_path[path] = max(best_score_by_path.get(path, 0.0), similarity)

    scored = [ScoredFile(path=p, score=s, reason="embedding") for p, s in best_score_by_path.items()]
    scored.sort(key=lambda sf: sf.score, reverse=True)
    return scored[:top_k]
