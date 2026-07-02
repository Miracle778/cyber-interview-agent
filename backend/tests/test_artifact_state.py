import pytest

from cyber_interview.domain.artifact import ArtifactStatus, InvalidTransition, transition_artifact


def test_draft_to_pending_approval():
    assert (
        transition_artifact(ArtifactStatus.DRAFT, ArtifactStatus.PENDING_APPROVAL)
        == ArtifactStatus.PENDING_APPROVAL
    )


def test_pending_approval_to_published():
    assert (
        transition_artifact(ArtifactStatus.PENDING_APPROVAL, ArtifactStatus.PUBLISHED)
        == ArtifactStatus.PUBLISHED
    )


def test_draft_to_published_is_invalid():
    with pytest.raises(InvalidTransition):
        transition_artifact(ArtifactStatus.DRAFT, ArtifactStatus.PUBLISHED)


def test_published_to_pending_approval_is_invalid():
    with pytest.raises(InvalidTransition):
        transition_artifact(ArtifactStatus.PUBLISHED, ArtifactStatus.PENDING_APPROVAL)
