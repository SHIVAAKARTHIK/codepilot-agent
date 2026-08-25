"""Embedding-search test. Uses Chroma's bundled local embedding model
(onnxruntime-based, no API key). The first run on a machine downloads it
(~79MB, cached under ~/.cache/chroma/); subsequent runs are fast.
"""
from src.codepilot.repo_explorer.repo_map import FileSummary
from src.codepilot.repo_explorer.retrieval import (
    embedding_search,
    index_files_for_embedding_search,
)


def test_embedding_search_finds_semantically_relevant_file(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "auth.py").write_text(
        "def login(username, password):\n"
        '    """Authenticate a user against the credentials store."""\n'
        "    return check_credentials(username, password)\n",
        encoding="utf-8",
    )
    (repo_root / "shapes.py").write_text(
        "def area_of_circle(radius):\n    return 3.14159 * radius * radius\n",
        encoding="utf-8",
    )

    files = [
        FileSummary(path="auth.py", language="python", exported_symbols=["login"], description="auth"),
        FileSummary(path="shapes.py", language="python", exported_symbols=["area_of_circle"], description="geometry"),
    ]
    persist_dir = tmp_path / "chroma"
    count = index_files_for_embedding_search(repo_root, files, persist_dir=persist_dir)
    assert count > 0

    results = embedding_search("how does user authentication work", persist_dir=persist_dir, top_k=2)

    assert results
    assert results[0].path == "auth.py"
    assert results[0].reason == "embedding"


def test_embedding_search_returns_empty_when_no_index_exists(tmp_path):
    results = embedding_search("anything", persist_dir=tmp_path / "no_index_here", top_k=5)
    assert results == []
