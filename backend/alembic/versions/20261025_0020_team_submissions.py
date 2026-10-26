"""Add team_submissions: the shared document a team hands in at session end,
with the AI's team score and the instructor's grade.

A new table, so init_db's create_all would also make it; the migration keeps
Alembic's history in step with the models.

Revision ID: 20261025_0020
Revises: 20261018_0019
Create Date: 2026-10-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_0020"
down_revision: Union[str, None] = "20261018_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "team_submissions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("group_session_id", sa.String(), sa.ForeignKey("group_sessions.id"), nullable=False),
        sa.Column("group_id", sa.String(), sa.ForeignKey("group_challenges.id"), nullable=False),
        sa.Column("challenge_id", sa.String(), sa.ForeignKey("challenges.id"), nullable=False),
        sa.Column("session_number", sa.Integer(), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=True),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column("ai_score_range", sa.JSON(), nullable=True),
        sa.Column("per_student", sa.JSON(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("instructor_score", sa.Float(), nullable=True),
        sa.Column("instructor_feedback", sa.Text(), nullable=True),
        sa.Column("graded_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("graded_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("group_session_id", name="uq_team_submission_session"),
    )
    op.create_index("ix_team_submissions_group_session_id", "team_submissions", ["group_session_id"])
    op.create_index("ix_team_submissions_group_id", "team_submissions", ["group_id"])
    op.create_index("ix_team_submissions_challenge_id", "team_submissions", ["challenge_id"])


def downgrade() -> None:
    op.drop_index("ix_team_submissions_challenge_id", table_name="team_submissions")
    op.drop_index("ix_team_submissions_group_id", table_name="team_submissions")
    op.drop_index("ix_team_submissions_group_session_id", table_name="team_submissions")
    op.drop_table("team_submissions")
