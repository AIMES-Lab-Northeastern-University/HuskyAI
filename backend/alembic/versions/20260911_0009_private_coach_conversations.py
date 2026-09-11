"""Private per-student coach conversations inside a group session.

A group session previously held exactly one Conversation: the team's shared coach
thread, owned by the team creator. Each student now also gets their own private
thread, so `conversations` needs a discriminator -- without one,
(group_session_id, user_id) collides for the team creator, who owns the shared
thread and also needs a private one.

  kind        solo | group_shared | group_private
  role_label  the student's role in the session, for role-tailored coaching

Uniqueness is a unique INDEX rather than a table constraint on purpose: SQLite
cannot add a constraint to an existing table, but CREATE UNIQUE INDEX works on
both engines, so the same guarantee reaches an already populated database. A NULL
group_session_id (every solo chat) is distinct in both engines, so solo
conversations stay unconstrained.

Existing rows are backfilled before the index is created: anything attached to a
group session becomes 'group_shared', everything else 'solo'. Creating the index
first would trip on un-classified rows.

As with 0007/0008: nothing runs `alembic upgrade` at deploy (nixpacks starts bare
uvicorn). init_db's defensive ALTER block is what actually reaches production --
and unlike the new artifact tables, this one genuinely needs it, because
create_all will not alter an existing populated table.

Revision ID: 20260911_0009
Revises: 20260911_0008
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0009"
down_revision: Union[str, None] = "20260911_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("kind", sa.String(length=24), nullable=False, server_default="solo"),
    )
    op.add_column("conversations", sa.Column("role_label", sa.String(length=64), nullable=True))

    # Classify what is already there before enforcing uniqueness.
    op.execute(
        "UPDATE conversations SET kind = 'group_shared' "
        "WHERE group_session_id IS NOT NULL AND kind = 'solo'"
    )

    op.create_index("ix_conversations_kind", "conversations", ["kind"])
    op.create_index(
        "uq_conversation_group_user_kind",
        "conversations",
        ["group_session_id", "user_id", "kind"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_conversation_group_user_kind", table_name="conversations")
    op.drop_index("ix_conversations_kind", table_name="conversations")
    op.drop_column("conversations", "role_label")
    op.drop_column("conversations", "kind")
