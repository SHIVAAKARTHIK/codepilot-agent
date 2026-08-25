import time
from pathlib import Path

from src.codepilot.repo_explorer.repo_map import build_or_load_repo_map, build_repo_map


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_sample_repo(root: Path) -> None:
    _write(
        root / "pkg" / "foo.py",
        '"""Foo module: does foo things."""\n\n\ndef helper(x):\n    return x + 1\n\n\nclass Foo:\n    pass\n',
    )
    _write(
        root / "pkg" / "bar.py",
        "# bar module, does bar things\n\ndef bar_fn():\n    pass\n",
    )
    _write(root / "README.md", "# Sample\nSome docs.\n")
    _write(root / "node_modules" / "ignored.py", "def should_not_appear():\n    pass\n")


def test_build_repo_map_extracts_symbols_and_descriptions(tmp_path):
    _make_sample_repo(tmp_path)
    repo_map = build_repo_map(tmp_path, token_budget=4000)

    paths = {f.path for f in repo_map.files}
    assert "pkg/foo.py" in paths
    assert "pkg/bar.py" in paths
    assert "README.md" in paths
    assert "node_modules/ignored.py" not in paths  # excluded dir

    foo = next(f for f in repo_map.files if f.path == "pkg/foo.py")
    assert "helper" in foo.exported_symbols
    assert "Foo" in foo.exported_symbols
    assert foo.description == "Foo module: does foo things."

    bar = next(f for f in repo_map.files if f.path == "pkg/bar.py")
    assert "bar_fn" in bar.exported_symbols
    assert bar.description == "bar module, does bar things"


def test_token_budget_forces_truncation(tmp_path):
    for i in range(20):
        _write(
            tmp_path / f"file_{i}.py",
            f'"""File number {i} with a fairly long description to burn tokens for the budget test."""\n\n'
            f"def fn_{i}():\n    pass\n",
        )

    repo_map = build_repo_map(tmp_path, token_budget=50)  # deliberately tiny

    assert repo_map.truncated is True
    assert len(repo_map.files) < 20
    assert repo_map.omitted_count == 20 - len(repo_map.files)
    assert repo_map.token_estimate() <= 50 or len(repo_map.files) <= 1


def test_build_or_load_reuses_cache_when_unchanged(tmp_path):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _make_sample_repo(repo_dir)

    first, was_cached_1 = build_or_load_repo_map(repo_dir, cache_dir=cache_dir, token_budget=4000)
    assert was_cached_1 is False

    second, was_cached_2 = build_or_load_repo_map(repo_dir, cache_dir=cache_dir, token_budget=4000)
    assert was_cached_2 is True
    assert second.fingerprint == first.fingerprint
    assert [f.path for f in second.files] == [f.path for f in first.files]


def test_build_or_load_invalidates_on_change(tmp_path):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _make_sample_repo(repo_dir)

    first, _ = build_or_load_repo_map(repo_dir, cache_dir=cache_dir, token_budget=4000)

    time.sleep(0.01)
    _write(repo_dir / "pkg" / "new_file.py", "def new_fn():\n    pass\n")

    second, was_cached = build_or_load_repo_map(repo_dir, cache_dir=cache_dir, token_budget=4000)
    assert was_cached is False
    assert second.fingerprint != first.fingerprint
    assert any(f.path == "pkg/new_file.py" for f in second.files)


def test_build_or_load_invalidates_on_token_budget_change(tmp_path):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _make_sample_repo(repo_dir)

    build_or_load_repo_map(repo_dir, cache_dir=cache_dir, token_budget=4000)
    _, was_cached = build_or_load_repo_map(repo_dir, cache_dir=cache_dir, token_budget=100)

    assert was_cached is False
