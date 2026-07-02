from cyber_interview.infra.models import (
    AgentRunRow,
    ArtifactRow,
    ArtifactVersionRow,
    ModelCallRow,
    RunAttemptRow,
    RunEventRow,
)


def test_six_models_importable():
    for cls in [
        ArtifactRow,
        ArtifactVersionRow,
        AgentRunRow,
        RunAttemptRow,
        RunEventRow,
        ModelCallRow,
    ]:
        assert cls.__tablename__


def test_artifact_version_status_values():
    assert {"draft", "pending_approval", "published"}.issubset(
        set(ArtifactVersionRow.status.type.enums)
    )
