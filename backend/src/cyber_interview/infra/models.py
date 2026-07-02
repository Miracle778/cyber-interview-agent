from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


ARTIFACT_STATUS = ["draft", "pending_approval", "published"]
RUN_STATUS = ["queued", "running", "completed", "failed"]
EVENT_TYPE = ["delta", "partial", "completed", "failed"]


class ArtifactRow(Base):
    __tablename__ = "artifact"
    __table_args__ = (
        CheckConstraint("workspace_id IS NOT NULL", name="ck_artifact_workspace_notnull"),
        UniqueConstraint("workspace_id", "kind", name="uq_artifact_workspace_kind"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class ArtifactVersionRow(Base):
    __tablename__ = "artifact_version"
    __table_args__ = (UniqueConstraint("artifact_id", "version_no", name="uq_artifact_version_no"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact.id", ondelete="RESTRICT"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_name: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(*ARTIFACT_STATUS, name="artifact_status"), nullable=False
    )
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AgentRunRow(Base):
    __tablename__ = "agent_run"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(String, nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(SAEnum(*RUN_STATUS, name="run_status"), nullable=False)
    command_id: Mapped[str | None] = mapped_column(String, nullable=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RunAttemptRow(Base):
    __tablename__ = "run_attempt"
    __table_args__ = (UniqueConstraint("run_id", "attempt_no", name="uq_run_attempt_no"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_run.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(SAEnum(*RUN_STATUS, name="attempt_status"), nullable=False)
    started_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ended_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RunEventRow(Base):
    __tablename__ = "run_event"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_run.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(SAEnum(*EVENT_TYPE, name="event_type"), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class ModelCallRow(Base):
    __tablename__ = "model_call"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("run_attempt.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd_micros: Mapped[int | None] = mapped_column(Integer, nullable=True)
