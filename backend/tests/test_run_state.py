import pytest

from cyber_interview.domain.run import InvalidRunTransition, RunStatus, transition_run


def test_queued_to_running():
    assert transition_run(RunStatus.QUEUED, RunStatus.RUNNING) == RunStatus.RUNNING


def test_running_to_completed():
    assert transition_run(RunStatus.RUNNING, RunStatus.COMPLETED) == RunStatus.COMPLETED


def test_running_to_failed():
    assert transition_run(RunStatus.RUNNING, RunStatus.FAILED) == RunStatus.FAILED


def test_queued_to_failed_gate_failure():
    assert transition_run(RunStatus.QUEUED, RunStatus.FAILED) == RunStatus.FAILED


def test_queued_to_completed_is_invalid():
    with pytest.raises(InvalidRunTransition):
        transition_run(RunStatus.QUEUED, RunStatus.COMPLETED)


def test_completed_to_running_is_invalid():
    with pytest.raises(InvalidRunTransition):
        transition_run(RunStatus.COMPLETED, RunStatus.RUNNING)
