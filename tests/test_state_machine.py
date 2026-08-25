import pytest

from src.codepilot.orchestrator.state_machine import (
    InvalidTransition,
    TaskState,
    TaskStateMachine,
)


def test_starts_in_triaged():
    sm = TaskStateMachine(issue_id="1")
    assert sm.state == TaskState.TRIAGED
    assert not sm.is_terminal()


def test_happy_path_sequence():
    sm = TaskStateMachine(issue_id="1")
    sm.transition(TaskState.EXPLORING)
    sm.transition(TaskState.IMPLEMENTING)
    sm.transition(TaskState.TESTING)
    sm.transition(TaskState.PR_OPENED)
    sm.transition(TaskState.DONE)
    assert sm.state == TaskState.DONE
    assert sm.is_terminal()
    assert len(sm.history) == 6  # initial + 5 transitions


def test_retry_loop_testing_back_to_implementing():
    sm = TaskStateMachine(issue_id="1")
    sm.transition(TaskState.EXPLORING)
    sm.transition(TaskState.IMPLEMENTING)
    sm.transition(TaskState.TESTING)
    sm.transition(TaskState.IMPLEMENTING, reason="tests failed, retry 1/3")
    assert sm.state == TaskState.IMPLEMENTING


@pytest.mark.parametrize("start", [TaskState.TRIAGED, TaskState.EXPLORING, TaskState.IMPLEMENTING, TaskState.TESTING, TaskState.PR_OPENED])
def test_any_non_terminal_state_can_fail(start):
    sm = TaskStateMachine(issue_id="1", state=start)
    sm.fail("guardrail violation")
    assert sm.state == TaskState.FAILED
    assert sm.is_terminal()


def test_illegal_skip_raises():
    sm = TaskStateMachine(issue_id="1")
    with pytest.raises(InvalidTransition):
        sm.transition(TaskState.DONE)  # can't skip straight from TRIAGED to DONE


def test_terminal_states_have_no_outgoing_transitions():
    sm = TaskStateMachine(issue_id="1", state=TaskState.DONE)
    with pytest.raises(InvalidTransition):
        sm.transition(TaskState.EXPLORING)
