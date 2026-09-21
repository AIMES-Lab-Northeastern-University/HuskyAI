"""Add verification_assignments + verification_responses (Phase 5).

Routes one student's contribution to a teammate for review and records whether
the check happened, was duplicated, or was skipped.

Outcomes are derived from read events rather than self-reported: "skipped"
includes the interesting case of a verdict submitted with no preceding read,
which is only detectable because Phase 1 logs reads as first-class events.

Additive; inert unless ClassroomChallenge.verification_policy is set.

Revision ID: 20260919_0012
Revises: 20260919_0011
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0012"
down_revision: Union[str, None] = "20260919_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "verification_assignments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_session_id", sa.String(), nullable=False),
        sa.Column("target_revision_id", sa.String(), nullable=False),
        sa.Column("target_section_key", sa.String(length=64), nullable=False),
        sa.Column("author_user_id", sa.String(), nullable=False),
        sa.Column("reviewer_user_id", sa.String(), nullable=False),
        sa.Column("routing_policy", sa.String(length=32), nullable=False, server_default="round_robin"),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
        sa.Column("due_turn", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.ForeignKeyConstraint(["group_session_id"], ["group_sessions.id"]),
        sa.ForeignKeyConstraint(["target_revision_id"], ["artifact_revisions.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("group_session_id", "target_revision_id", "author_user_id", "reviewer_user_id"):
        op.create_index(f"ix_verif_assign_{col}", "verification_assignments", [col])

    op.create_table(
        "verification_responses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("assignment_id", sa.String(), nullable=False),
        sa.Column("reviewer_user_id", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("checked_against_corpus", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_refs", sa.JSON(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["assignment_id"], ["verification_assignments.id"]),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verif_resp_assignment", "verification_responses", ["assignment_id"])
    op.create_index("ix_verif_resp_reviewer", "verification_responses", ["reviewer_user_id"])


def downgrade() -> None:
    op.drop_index("ix_verif_resp_reviewer", table_name="verification_responses")
    op.drop_index("ix_verif_resp_assignment", table_name="verification_responses")
    op.drop_table("verification_responses")
    for col in ("reviewer_user_id", "author_user_id", "target_revision_id", "group_session_id"):
        op.drop_index(f"ix_verif_assign_{col}", table_name="verification_assignments")
    op.drop_table("verification_assignments")
