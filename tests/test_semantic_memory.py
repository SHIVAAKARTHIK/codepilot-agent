from src.codepilot.memory.semantic import SemanticMemory, lessons_to_prompt_block


def test_record_and_retrieve_similar_lesson(tmp_path):
    mem = SemanticMemory(persist_dir=tmp_path)
    mem.record_lesson(
        repo="acme/demo",
        task_type="bug_fix",
        issue_summary="Crash when the input list is empty",
        approach="Added a guard clause returning an empty result for empty input.",
        files_changed=["src/summarize.py"],
    )

    results = mem.retrieve_similar_lessons(
        repo="acme/demo", task_type="bug_fix", query="function crashes on empty list input", top_k=3
    )

    assert len(results) == 1
    assert results[0].issue_summary == "Crash when the input list is empty"
    assert results[0].files_changed == ["src/summarize.py"]


def test_retrieval_filters_by_repo(tmp_path):
    mem = SemanticMemory(persist_dir=tmp_path)
    mem.record_lesson(
        repo="acme/demo-a", task_type="bug_fix", issue_summary="Null pointer crash",
        approach="Added null check.", files_changed=["a.py"],
    )
    mem.record_lesson(
        repo="acme/demo-b", task_type="bug_fix", issue_summary="Null pointer crash",
        approach="Added null check.", files_changed=["b.py"],
    )

    results = mem.retrieve_similar_lessons(repo="acme/demo-a", task_type="bug_fix", query="null pointer crash")

    assert len(results) == 1
    assert results[0].files_changed == ["a.py"]


def test_retrieval_filters_by_task_type(tmp_path):
    mem = SemanticMemory(persist_dir=tmp_path)
    mem.record_lesson(
        repo="acme/demo", task_type="bug_fix", issue_summary="Fix crash",
        approach="Fixed it.", files_changed=["a.py"],
    )
    mem.record_lesson(
        repo="acme/demo", task_type="feature_addition", issue_summary="Fix crash",
        approach="Added feature.", files_changed=["b.py"],
    )

    results = mem.retrieve_similar_lessons(repo="acme/demo", task_type="bug_fix", query="fix crash")

    assert len(results) == 1
    assert results[0].task_type == "bug_fix"


def test_retrieval_respects_top_k(tmp_path):
    mem = SemanticMemory(persist_dir=tmp_path)
    for i in range(5):
        mem.record_lesson(
            repo="acme/demo", task_type="bug_fix", issue_summary=f"Bug number {i}",
            approach="Fixed it.", files_changed=[f"f{i}.py"],
        )

    results = mem.retrieve_similar_lessons(repo="acme/demo", task_type="bug_fix", query="bug", top_k=3)

    assert len(results) == 3


def test_retrieval_empty_when_nothing_recorded(tmp_path):
    mem = SemanticMemory(persist_dir=tmp_path)
    assert mem.retrieve_similar_lessons(repo="acme/demo", task_type="bug_fix", query="anything") == []


def test_lessons_to_prompt_block_empty():
    assert lessons_to_prompt_block([]) == ""


def test_lessons_to_prompt_block_includes_content(tmp_path):
    mem = SemanticMemory(persist_dir=tmp_path)
    mem.record_lesson(
        repo="acme/demo", task_type="bug_fix", issue_summary="Crash on empty list",
        approach="Added a guard clause.", files_changed=["a.py"],
    )
    lessons = mem.retrieve_similar_lessons(repo="acme/demo", task_type="bug_fix", query="crash on empty list")

    block = lessons_to_prompt_block(lessons)

    assert "Crash on empty list" in block
    assert "Added a guard clause." in block
    assert "a.py" in block
