from src.codepilot.coder.sandbox import cleanup_sandbox, create_sandbox


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_create_sandbox_copies_only_relevant_files(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "pkg" / "foo.py", "print('foo')\n")
    _write(repo_root / "pkg" / "bar.py", "print('bar')\n")
    _write(repo_root / "secrets.env", "SECRET=1\n")

    sandbox_base = tmp_path / "sandboxes"
    sandbox_dir = create_sandbox(
        repo_root, ["pkg/foo.py"], sandbox_base=sandbox_base, issue_id="42"
    )

    assert (sandbox_dir / "pkg" / "foo.py").exists()
    assert (sandbox_dir / "pkg" / "foo.py").read_text(encoding="utf-8") == "print('foo')\n"
    assert not (sandbox_dir / "pkg" / "bar.py").exists()  # not in relevant_files
    assert not (sandbox_dir / "secrets.env").exists()


def test_create_sandbox_ignores_missing_files(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "a.py", "x = 1\n")

    sandbox_dir = create_sandbox(
        repo_root, ["a.py", "does_not_exist.py"], sandbox_base=tmp_path / "sandboxes", issue_id="1"
    )

    assert (sandbox_dir / "a.py").exists()
    assert not (sandbox_dir / "does_not_exist.py").exists()


def test_create_sandbox_is_fresh_on_rerun(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "a.py", "x = 1\n")
    sandbox_base = tmp_path / "sandboxes"

    sandbox_dir = create_sandbox(repo_root, ["a.py"], sandbox_base=sandbox_base, issue_id="1")
    (sandbox_dir / "leftover.txt").write_text("stale", encoding="utf-8")

    sandbox_dir_2 = create_sandbox(repo_root, ["a.py"], sandbox_base=sandbox_base, issue_id="1")

    assert sandbox_dir_2 == sandbox_dir
    assert not (sandbox_dir_2 / "leftover.txt").exists()  # wiped, not reused


def test_cleanup_sandbox_removes_directory(tmp_path):
    repo_root = tmp_path / "repo"
    _write(repo_root / "a.py", "x = 1\n")
    sandbox_dir = create_sandbox(repo_root, ["a.py"], sandbox_base=tmp_path / "sandboxes", issue_id="1")

    assert sandbox_dir.exists()
    cleanup_sandbox(sandbox_dir)
    assert not sandbox_dir.exists()
