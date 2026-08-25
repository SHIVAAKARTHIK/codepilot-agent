from src.codepilot.repo_explorer.repo_map import FileSummary, RepoMap
from src.codepilot.repo_explorer.retrieval import keyword_search


def _map_with(files: list[FileSummary]) -> RepoMap:
    return RepoMap(repo_root="/x", fingerprint="f", generated_at="now", token_budget=4000, files=files)


def test_keyword_search_ranks_symbol_matches_above_text_matches():
    files = [
        FileSummary(path="a/auth.py", language="python", exported_symbols=["login"], description="handles auth flow"),
        FileSummary(path="b/misc.py", language="python", exported_symbols=[], description="unrelated utilities"),
        FileSummary(path="c/other.py", language="python", exported_symbols=[], description="mentions login in passing"),
    ]
    results = keyword_search(_map_with(files), "login", top_k=5)

    assert results[0].path == "a/auth.py"  # symbol match scores highest
    paths = [r.path for r in results]
    assert "b/misc.py" not in paths  # no match at all -> excluded


def test_keyword_search_empty_query_returns_nothing():
    files = [FileSummary(path="a.py", language="python", description="x")]
    assert keyword_search(_map_with(files), "", top_k=5) == []


def test_keyword_search_respects_top_k():
    files = [FileSummary(path=f"f{i}.py", language="python", description="login handler") for i in range(20)]
    results = keyword_search(_map_with(files), "login", top_k=3)
    assert len(results) == 3


def test_keyword_search_no_match_returns_empty():
    files = [FileSummary(path="a.py", language="python", description="totally unrelated content")]
    assert keyword_search(_map_with(files), "quantum flux capacitor", top_k=5) == []
