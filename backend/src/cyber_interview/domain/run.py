from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InvalidRunTransition(Exception):
    pass


_RUN_TRANSITIONS: set[tuple[RunStatus, RunStatus]] = {
    (RunStatus.QUEUED, RunStatus.RUNNING),
    (RunStatus.RUNNING, RunStatus.COMPLETED),
    (RunStatus.RUNNING, RunStatus.FAILED),
    (RunStatus.QUEUED, RunStatus.FAILED),
}


def transition_run(current: RunStatus, target: RunStatus) -> RunStatus:
    if (current, target) not in _RUN_TRANSITIONS:
        raise InvalidRunTransition(f"{current.value} -> {target.value} not allowed")
    return target
