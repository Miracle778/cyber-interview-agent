from enum import StrEnum


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    PUBLISHED = "published"


class InvalidTransition(Exception):
    """Raised when a state transition is not allowed."""


_ARTIFACT_TRANSITIONS: set[tuple[ArtifactStatus, ArtifactStatus]] = {
    (ArtifactStatus.DRAFT, ArtifactStatus.PENDING_APPROVAL),
    (ArtifactStatus.PENDING_APPROVAL, ArtifactStatus.PUBLISHED),
}


def transition_artifact(current: ArtifactStatus, target: ArtifactStatus) -> ArtifactStatus:
    if (current, target) not in _ARTIFACT_TRANSITIONS:
        raise InvalidTransition(f"{current.value} -> {target.value} not allowed")
    return target
