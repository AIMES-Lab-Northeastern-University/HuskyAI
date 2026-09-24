"""Add study_events: the collaborative-study event log.

One ordered, append-only record of every action in a session, including reads of
a teammate's work. `seq` is monotonic per session scope (group_sessions for
collaborative work, user_challenge_sessions for the solo control arm) and is the
basis for every turn-taking metric, so both scopes get a unique (scope, seq)
constraint as a backstop against a double allocation.

Purely additive: no existing table is touched, so the solo and group flows are
unaffected until call sites start emitting.

Revision ID: 20260919_0007
Revises: 20260815_0006
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0007"
down_revision: Union[str, None] = "20260815_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_session_id", sa.String(), nullable=True),
        sa.Column("user_challenge_session_id", sa.String(), nullable=True),
        sa.Column("classroom_id", sa.String(), nullable=True),
        sa.Column("challenge_id", sa.String(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("role_label", sa.String(length=64), nullable=True),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("ref_id", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("client_ts", sa.DateTime(), nullable=True),
        sa.Column("server_ts", sa.DateTime(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("consent_research", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("condition", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["group_session_id"], ["group_sessions.id"]),
        sa.ForeignKeyConstraint(["user_challenge_session_id"], ["user_challenge_sessions.id"]),
        sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"]),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_session_id", "seq", name="uq_study_event_group_seq"),
        sa.UniqueConstraint("user_challenge_session_id", "seq", name="uq_study_event_solo_seq"),
        sa.UniqueConstraint("idempotency_key", name="uq_study_event_idempotency"),
    )
    op.create_index("ix_study_events_group_session_id", "study_events", ["group_session_id"])
    op.create_index(
        "ix_study_events_user_challenge_session_id", "study_events", ["user_challenge_session_id"]
    )
    op.create_index("ix_study_events_classroom_id", "study_events", ["classroom_id"])
    op.create_index("ix_study_events_challenge_id", "study_events", ["challenge_id"])
    op.create_index("ix_study_events_actor_user_id", "study_events", ["actor_user_id"])
    op.create_index("ix_study_events_target", "study_events", ["target"])
    op.create_index("ix_study_events_action", "study_events", ["action"])


def downgrade() -> None:
    op.drop_index("ix_study_events_action", table_name="study_events")
    op.drop_index("ix_study_events_target", table_name="study_events")
    op.drop_index("ix_study_events_actor_user_id", table_name="study_events")
    op.drop_index("ix_study_events_challenge_id", table_name="study_events")
    op.drop_index("ix_study_events_classroom_id", table_name="study_events")
    op.drop_index("ix_study_events_user_challenge_session_id", table_name="study_events")
    op.drop_index("ix_study_events_group_session_id", table_name="study_events")
    op.drop_table("study_events")
