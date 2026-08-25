from src.codepilot.memory.episodic import EpisodicMemory, TaskLogEntry


def test_log_task_and_end_session(tmp_path):
    persist_path = tmp_path / "episodic.json"
    mem = EpisodicMemory(persist_path=persist_path)
    mem.log_task(
        TaskLogEntry(
            issue_id="1",
            task_type="bug_fix",
            files_modified=["a.py"],
            outcome="DONE",
            duration_seconds=12.5,
        )
    )
    summary = mem.end_session()

    assert summary.session_id == mem.session_id
    assert len(summary.tasks) == 1
    assert persist_path.exists()


def test_recent_session_summaries_reads_across_instances(tmp_path):
    persist_path = tmp_path / "episodic.json"

    first = EpisodicMemory(persist_path=persist_path)
    first.log_task(
        TaskLogEntry(issue_id="1", task_type="bug_fix", files_modified=[], outcome="DONE", duration_seconds=1)
    )
    first.end_session()

    # A brand-new process/instance should see the prior session via the
    # persistence shim, proving "read at startup" survives a restart.
    second = EpisodicMemory(persist_path=persist_path)
    summaries = second.recent_session_summaries(limit=3)

    assert len(summaries) == 1
    assert summaries[0]["session_id"] == first.session_id


def test_recently_failed_issue_ids_across_instances(tmp_path):
    persist_path = tmp_path / "episodic.json"

    first = EpisodicMemory(persist_path=persist_path)
    first.log_task(
        TaskLogEntry(issue_id="9", task_type="bug_fix", files_modified=[], outcome="FAILED", duration_seconds=1)
    )
    first.log_task(
        TaskLogEntry(issue_id="10", task_type="bug_fix", files_modified=[], outcome="DONE", duration_seconds=1)
    )
    first.end_session()

    second = EpisodicMemory(persist_path=persist_path)
    failed = second.recently_failed_issue_ids()

    assert failed == {"9"}


def test_limit_3_sessions_enforced(tmp_path):
    persist_path = tmp_path / "episodic.json"

    for i in range(5):
        mem = EpisodicMemory(persist_path=persist_path)
        mem.log_task(
            TaskLogEntry(issue_id=str(i), task_type="bug_fix", files_modified=[], outcome="DONE", duration_seconds=1)
        )
        mem.end_session()

    final = EpisodicMemory(persist_path=persist_path)
    assert len(final.recent_session_summaries(limit=3)) == 3
