from src.codepilot.orchestrator.in_progress import InProgressTracker


def test_mark_and_check():
    tracker = InProgressTracker()
    assert not tracker.is_in_progress("1")
    tracker.mark("1")
    assert tracker.is_in_progress("1")
    assert len(tracker) == 1


def test_unmark():
    tracker = InProgressTracker()
    tracker.mark("1")
    tracker.unmark("1")
    assert not tracker.is_in_progress("1")
    assert len(tracker) == 0


def test_unmark_missing_id_is_a_noop():
    tracker = InProgressTracker()
    tracker.unmark("does-not-exist")  # should not raise
    assert len(tracker) == 0
