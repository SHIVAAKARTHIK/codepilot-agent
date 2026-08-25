from src.codepilot.memory.working import WorkingMemory


def _make() -> WorkingMemory:
    return WorkingMemory(issue_id="42", issue_title="Fix null check", issue_body="Full raw body text...")


def test_record_classification():
    wm = _make()
    wm.record_classification("bug_fix")
    assert wm.task_type == "bug_fix"


def test_record_relevant_files_copies_list():
    wm = _make()
    files = ["a.py", "b.py"]
    wm.record_relevant_files(files)
    files.append("c.py")
    assert wm.relevant_files == ["a.py", "b.py"]  # not aliased to caller's list


def test_retry_counter_increments():
    wm = _make()
    assert wm.increment_retry() == 1
    assert wm.increment_retry() == 2
    assert wm.retry_count == 2


def test_record_test_result():
    wm = _make()
    wm.record_test_result(passed=False, details={"failures": ["test_x"]})
    assert wm.test_results == {"passed": False, "failures": ["test_x"]}


def test_subagent_context_excludes_raw_body():
    """Context engineering rule: subagent spawns get paths/facts, never raw
    file/issue content inline."""
    wm = _make()
    wm.record_classification("bug_fix")
    wm.record_relevant_files(["src/foo.py"])
    ctx = wm.to_subagent_context()
    assert "issue_body" not in ctx
    assert ctx["relevant_files"] == ["src/foo.py"]
    assert ctx["task_type"] == "bug_fix"
