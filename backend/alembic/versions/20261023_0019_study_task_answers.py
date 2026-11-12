"""Add study_task_answers.

The end-of-task questions of Lucy's study (correct total, corrections made,
confidence), answered in HuskyAI when a task ends. One row per participant and
task, never updated: the unique constraint is the lock.

New table only; no existing table is altered. Inert unless STUDY_MODE_ENABLED
is set.

Revision ID: 20261023_0019
Revises: 20261016_0018
Create Date: 2026-10-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0019"
down_revision: Union[str, None] = "20261016_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_task_answers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("participant_id", sa.String(), sa.ForeignKey("study_participants.id"),
                  nullable=False),
        sa.Column("task", sa.Integer(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("user_challenge_session_id", sa.String(),
                  sa.ForeignKey("user_challenge_sessions.id"), nullable=True),
        sa.Column("total", sa.String(length=32), nullable=False),
        sa.Column("corrections", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("participant_id", "task", name="uq_study_task_answer"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 100",
                           name="ck_study_task_answer_confidence"),
    )
    op.create_index("ix_study_task_answers_participant_id", "study_task_answers",
                    ["participant_id"])


def downgrade() -> None:
    op.drop_index("ix_study_task_answers_participant_id", table_name="study_task_answers")
    op.drop_table("study_task_answers")
