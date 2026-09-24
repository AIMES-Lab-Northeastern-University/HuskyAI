"""Add Conversation.kind: solo | group_shared | coach_private.

Private per-student coach conversations inside a group session need no new
table — a Conversation already carries both user_id and a nullable
group_session_id, so setting both and marking kind='coach_private' is enough.

Defaults to 'solo', so every existing row keeps its current meaning.

Revision ID: 20260919_0009
Revises: 20260919_0008
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0009"
down_revision: Union[str, None] = "20260919_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="solo"),
    )
    # Legacy team chats are identifiable by their group link; label them so the
    # new per-student coaches are distinguishable from the old shared model.
    op.execute(
        "UPDATE conversations SET kind = 'group_shared' WHERE group_session_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("conversations", "kind")
