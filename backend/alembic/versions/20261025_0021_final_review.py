"""Final review before a team session ends: when it started, and who is ready.

Revision ID: 20261025_0021
Revises: 20261025_0020
Create Date: 2026-10-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_0021"
down_revision: Union[str, None] = "20261025_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("group_sessions", sa.Column("review_started_at", sa.DateTime(), nullable=True))
    op.create_table(
        "review_ready_marks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("group_session_id", sa.String(), sa.ForeignKey("group_sessions.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("group_session_id", "user_id", name="uq_review_ready_mark"),
    )
    op.create_index("ix_review_ready_marks_group_session_id", "review_ready_marks", ["group_session_id"])


def downgrade() -> None:
    op.drop_index("ix_review_ready_marks_group_session_id", table_name="review_ready_marks")
    op.drop_table("review_ready_marks")
    op.drop_column("group_sessions", "review_started_at")
