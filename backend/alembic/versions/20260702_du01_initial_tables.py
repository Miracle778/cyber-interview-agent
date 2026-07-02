"""du01 initial tables

Revision ID: 20260702_du01
Revises:
Create Date: 2026-07-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20260702_du01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("workspace_id IS NOT NULL", name="ck_artifact_workspace_notnull"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "kind", name="uq_artifact_workspace_kind"),
    )
    op.create_table(
        "artifact_version",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("schema_name", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "pending_approval", "published", name="artifact_status"),
            nullable=False,
        ),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifact.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "version_no", name="uq_artifact_version_no"),
    )
    op.create_index(
        "uq_artifact_one_published",
        "artifact_version",
        ["artifact_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.Column("thread_id", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "completed", "failed", name="run_status"),
            nullable=False,
        ),
        sa.Column("command_id", sa.String(), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifact.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "run_attempt",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "completed", "failed", name="attempt_status"),
            nullable=False,
        ),
        sa.Column("started_at", sa.Integer(), nullable=True),
        sa.Column("ended_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "attempt_no", name="uq_run_attempt_no"),
    )
    op.create_table(
        "run_event",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum("delta", "partial", "completed", "failed", name="event_type"),
            nullable=False,
        ),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),
    )
    op.create_table(
        "model_call",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd_micros", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["attempt_id"], ["run_attempt.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("model_call")
    op.drop_table("run_event")
    op.drop_table("run_attempt")
    op.drop_table("agent_run")
    op.drop_index("uq_artifact_one_published", table_name="artifact_version")
    op.drop_table("artifact_version")
    op.drop_table("artifact")
