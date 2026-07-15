"""Add group-challenge tables + Conversation.group_session_id + Message.sender_user_id.

Group challenges let 2-4 students share one conversation/PEI per session, with the
team persisting across all of a challenge's sessions. New tables: group_challenges,
group_members, group_sessions. Existing tables gain nullable links so the single-user
flow is unaffected.

Revision ID: 20260618_0004
Revises: 20260613_0003
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260618_0004"
down_revision: Union[str, None] = "20260613_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_challenges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("join_code", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("max_members", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("join_code"),
    )
    op.create_index("ix_group_challenges_challenge_id", "group_challenges", ["challenge_id"])
    op.create_index("ix_group_challenges_join_code", "group_challenges", ["join_code"])
    op.create_index("ix_group_challenges_created_by", "group_challenges", ["created_by"])

    op.create_table(
        "group_members",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["group_challenges.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])

    op.create_table(
        "group_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_id", sa.String(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("session_number", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("best_pei", sa.Float(), nullable=True),
        sa.Column("session_avg_pei", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True, server_default="not_started"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("end_reason", sa.String(length=16), nullable=True),
        sa.Column("time_limit_minutes", sa.Integer(), nullable=True),
        sa.Column("min_turns", sa.Integer(), nullable=True),
        sa.Column("session_analysis", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["group_challenges.id"]),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "session_number", name="uq_group_session_num"),
    )
    op.create_index("ix_group_sessions_group_id", "group_sessions", ["group_id"])
    op.create_index("ix_group_sessions_challenge_id", "group_sessions", ["challenge_id"])

    # Nullable links on existing tables; null for the single-user flow.
    op.add_column("conversations", sa.Column("group_session_id", sa.String(), nullable=True))
    op.create_index("ix_conversations_group_session_id", "conversations", ["group_session_id"])
    op.create_foreign_key(
        "fk_conversations_group_session_id", "conversations", "group_sessions",
        ["group_session_id"], ["id"],
    )

    op.add_column("messages", sa.Column("sender_user_id", sa.String(), nullable=True))
    op.create_index("ix_messages_sender_user_id", "messages", ["sender_user_id"])
    op.create_foreign_key(
        "fk_messages_sender_user_id", "messages", "users",
        ["sender_user_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_messages_sender_user_id", "messages", type_="foreignkey")
    op.drop_index("ix_messages_sender_user_id", table_name="messages")
    op.drop_column("messages", "sender_user_id")

    op.drop_constraint("fk_conversations_group_session_id", "conversations", type_="foreignkey")
    op.drop_index("ix_conversations_group_session_id", table_name="conversations")
    op.drop_column("conversations", "group_session_id")

    op.drop_index("ix_group_sessions_challenge_id", table_name="group_sessions")
    op.drop_index("ix_group_sessions_group_id", table_name="group_sessions")
    op.drop_table("group_sessions")

    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_index("ix_group_members_group_id", table_name="group_members")
    op.drop_table("group_members")

    op.drop_index("ix_group_challenges_created_by", table_name="group_challenges")
    op.drop_index("ix_group_challenges_join_code", table_name="group_challenges")
    op.drop_index("ix_group_challenges_challenge_id", table_name="group_challenges")
    op.drop_table("group_challenges")
