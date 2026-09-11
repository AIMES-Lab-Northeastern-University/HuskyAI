"""Artifact read/write event log.

artifact_events is the permanent, append-only research record. Reads and writes
share ONE monotonic `seq` per group session so that "did the student read a
teammate's section before or after writing their own" is answerable; separate
timelines would make it unanswerable.

Coach reads are kept structurally distinct from human reads by actor_kind plus a
CHECK constraint: a coach/system event may not carry a user, and a student event
must. Combined with the separate append helpers in artifact_events.py, there is
no path that records a coach read as a human one.

artifact_read_heartbeats holds raw dwell samples. It is the only prunable /
sheddable tier; artifact_events is never pruned, and any shedding appends a
heartbeat_shed event to artifact_events so the loss is visible.

As with 0007: nothing runs `alembic upgrade` at deploy (nixpacks starts bare
uvicorn), so init_db's create_all is what actually builds these. This revision
keeps the history honest.

Revision ID: 20260911_0008
Revises: 20260911_0007
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0008"
down_revision: Union[str, None] = "20260911_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifact_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("group_session_id", sa.String(), sa.ForeignKey("group_sessions.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("section_key", sa.String(length=128), nullable=True),
        sa.Column("client_ts", sa.DateTime(), nullable=True),
        sa.Column("server_ts", sa.DateTime(), nullable=False),
        sa.Column("dwell_ms", sa.Integer(), nullable=True),
        sa.Column("surface", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.UniqueConstraint("group_session_id", "seq", name="uq_artifact_event_seq"),
        sa.UniqueConstraint("group_session_id", "idempotency_key", name="uq_artifact_event_idem"),
        sa.CheckConstraint(
            "(actor_kind = 'student' AND actor_user_id IS NOT NULL) OR "
            "(actor_kind IN ('coach', 'system') AND actor_user_id IS NULL)",
            name="ck_artifact_event_actor",
        ),
    )
    op.create_index("ix_artifact_events_group_session_id", "artifact_events", ["group_session_id"])
    op.create_index("ix_artifact_events_event_type", "artifact_events", ["event_type"])
    op.create_index("ix_artifact_events_actor_kind", "artifact_events", ["actor_kind"])
    op.create_index("ix_artifact_events_actor_user_id", "artifact_events", ["actor_user_id"])

    op.create_table(
        "artifact_read_heartbeats",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("group_session_id", sa.String(), sa.ForeignKey("group_sessions.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("section_key", sa.String(length=128), nullable=False),
        sa.Column("visible_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_artifact_read_heartbeats_group_session_id", "artifact_read_heartbeats", ["group_session_id"])
    op.create_index("ix_artifact_read_heartbeats_at", "artifact_read_heartbeats", ["at"])


def downgrade() -> None:
    op.drop_table("artifact_read_heartbeats")
    op.drop_table("artifact_events")
