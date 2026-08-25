from src.codepilot.pr_agent.formatting import branch_name, commit_message, pr_body, pr_title, slugify


def test_slugify_basic():
    assert slugify("Fix null pointer!! in parser") == "fix-null-pointer-in-parser"


def test_slugify_truncates_and_strips_trailing_dash():
    slug = slugify("a" * 100, max_len=10)
    assert len(slug) <= 10
    assert not slug.endswith("-")


def test_slugify_empty_falls_back():
    assert slugify("!!!") == "task"


def test_branch_name_format():
    assert branch_name(42, "Fix crash on empty list") == "codepilot/issue-42-fix-crash-on-empty-list"


def test_commit_message_structure():
    msg = commit_message(
        issue_number=7,
        summary="fix null check",
        what_changed=["added guard clause", "added test"],
        why="prevents crash on empty input",
    )
    assert msg.startswith("fix(#7): fix null check")
    assert "- added guard clause" in msg
    assert "- added test" in msg
    assert "- prevents crash on empty input" in msg
    assert msg.strip().endswith("Closes #7")


def test_pr_title_format():
    assert pr_title("Fix crash on empty list") == "[CodePilot] Fix crash on empty list"


def test_pr_body_includes_all_required_sections():
    body = pr_body(
        issue_number=5,
        issue_url="https://github.com/acme/demo/issues/5",
        approach="Added a null check.",
        files_changed=["a.py", "b.py"],
        test_summary="PASSED: 3 passed",
    )
    assert "Added a null check." in body
    assert "`a.py`" in body
    assert "`b.py`" in body
    assert "PASSED: 3 passed" in body
    assert "Closes #5" in body
    assert "https://github.com/acme/demo/issues/5" in body
