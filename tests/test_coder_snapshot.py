"""Tests for the Coder's before/after snapshot + diff generation -
specifically that generated/compiled artifacts (which can appear once the
Coder actually runs code, e.g. `__pycache__/*.pyc`) never pollute the diff
a human is supposed to review.
"""
from src.codepilot.coder.agent import _snapshot, generate_unified_diff


def _write(path, content=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def test_snapshot_excludes_pycache_dir(tmp_path):
    _write(tmp_path / "calc.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path / "__pycache__" / "calc.cpython-313.pyc", b"\x00\x01garbage")

    snapshot = _snapshot(tmp_path)

    assert "calc.py" in snapshot
    assert not any("__pycache__" in path for path in snapshot)


def test_snapshot_excludes_pyc_suffix_anywhere(tmp_path):
    _write(tmp_path / "stray.pyc", b"\x00\x01garbage")
    _write(tmp_path / "calc.py", "x = 1\n")

    snapshot = _snapshot(tmp_path)

    assert "calc.py" in snapshot
    assert "stray.pyc" not in snapshot


def test_snapshot_excludes_pytest_cache_dir(tmp_path):
    _write(tmp_path / ".pytest_cache" / "v" / "cache" / "lastfailed", "{}")
    _write(tmp_path / "test_calc.py", "def test_x():\n    assert True\n")

    snapshot = _snapshot(tmp_path)

    assert "test_calc.py" in snapshot
    assert not any(".pytest_cache" in path for path in snapshot)


def test_snapshot_excludes_working_dir(tmp_path):
    _write(tmp_path / "working" / "proposed_diff.txt", "some diff")
    _write(tmp_path / "calc.py", "x = 1\n")

    snapshot = _snapshot(tmp_path)

    assert "calc.py" in snapshot
    assert not any(path.startswith("working/") for path in snapshot)


def test_generate_unified_diff_shows_only_changed_files():
    before = {"a.py": "x = 1\n", "b.py": "y = 2\n"}
    after = {"a.py": "x = 2\n", "b.py": "y = 2\n"}  # b.py unchanged

    diff = generate_unified_diff(before, after)

    assert "a/a.py" in diff
    assert "a/b.py" not in diff
    assert "-x = 1" in diff
    assert "+x = 2" in diff
