"""Instructor-driven group challenge redesign.

Group challenges move from student-initiated (shared join code) to instructor-driven:
- classroom_challenges gains assignment-level group mode (mode/team_min/team_max),
  so the same challenge can be solo in one section and group in another.
- group_challenges (a team) becomes classroom-scoped (classroom_id) with an optional
  name; the old join_code is retired (made nullable — prof-assigned teams leave it NULL).
- new group_chat_messages table holds the team backchannel (student-to-student
  discussion), kept separate from the coach conversation so it never reaches the LLM,
  the evaluator, or the training export.

Revision ID: 20260621_0005
Revises: 20260618_0004
Create Date: 2026-06-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260621_0005"
down_revision: Union[str, None] = "20260618_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Assignment-level group mode. Defaults keep existing assignments solo.
    op.add_column(
        "classroom_challenges",
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="solo"),
    )
    op.add_column(
        "classroom_challenges",
        sa.Column("team_min", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "classroom_challenges",
        sa.Column("team_max", sa.Integer(), nullable=False, server_default="4"),
    )

    # Team becomes classroom-scoped; join_code retired (nullable).
    op.add_column("group_challenges", sa.Column("classroom_id", sa.String(), nullable=True))
    op.add_column("group_challenges", sa.Column("name", sa.String(length=200), nullable=True))
    op.create_index("ix_group_challenges_classroom_id", "group_challenges", ["classroom_id"])
    op.create_foreign_key(
        "fk_group_challenges_classroom_id", "group_challenges", "classrooms",
        ["classroom_id"], ["id"],
    )
    op.alter_column("group_challenges", "join_code", existing_type=sa.String(length=16), nullable=True)

    # Team backchannel (human-only; never linked to conversations/messages).
    op.create_table(
        "group_chat_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_id", sa.String(), nullable=False),
        sa.Column("sender_user_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["group_challenges.id"]),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_group_chat_messages_group_id", "group_chat_messages", ["group_id"])
    op.create_index("ix_group_chat_messages_sender_user_id", "group_chat_messages", ["sender_user_id"])
    op.create_index("ix_group_chat_messages_created_at", "group_chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_group_chat_messages_created_at", table_name="group_chat_messages")
    op.drop_index("ix_group_chat_messages_sender_user_id", table_name="group_chat_messages")
    op.drop_index("ix_group_chat_messages_group_id", table_name="group_chat_messages")
    op.drop_table("group_chat_messages")

    op.alter_column("group_challenges", "join_code", existing_type=sa.String(length=16), nullable=False)
    op.drop_constraint("fk_group_challenges_classroom_id", "group_challenges", type_="foreignkey")
    op.drop_index("ix_group_challenges_classroom_id", table_name="group_challenges")
    op.drop_column("group_challenges", "name")
    op.drop_column("group_challenges", "classroom_id")

    op.drop_column("classroom_challenges", "team_max")
    op.drop_column("classroom_challenges", "team_min")
    op.drop_column("classroom_challenges", "mode")
