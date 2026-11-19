"""Add study_participants.

Anonymous participants for the cognitive-offloading study: each is backed by a
User row and holds a hashed sign-in code, a condition fixed at creation, the
current block, and the seeded task order.

New table only; no existing table is altered. Inert unless STUDY_MODE_ENABLED
is set and codes have been minted.

Revision ID: 20261010_0017
Revises: 20260928_0016
Create Date: 2026-10-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261010_0017"
down_revision: Union[str, None] = "20260928_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_participants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("condition", sa.String(length=16), nullable=False),
        sa.Column("current_block", sa.String(length=16), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("task_order", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_study_participant_user"),
        sa.UniqueConstraint("code_hash", name="uq_study_participant_code_hash"),
        sa.CheckConstraint(
            "condition IN ('feedback', 'no_feedback')", name="ck_study_participant_condition"
        ),
        sa.CheckConstraint(
            "current_block IN ('pretest', 'training', 'posttest', 'done')",
            name="ck_study_participant_block",
        ),
    )


def downgrade() -> None:
    op.drop_table("study_participants")
