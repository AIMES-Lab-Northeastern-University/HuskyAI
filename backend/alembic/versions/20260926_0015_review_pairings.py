"""Add review_pairings and verification_assignments.replaces_assignment_id.

Makes the instructor_assigned verification policy real. Until now it was
accepted by the settings endpoint and offered in the instructor UI, but routing
only special-cased "random", so it silently ran round-robin.

- review_pairings: who reviews whose work, per team, set before the session.
- replaces_assignment_id: links a review an instructor reassigned mid-session
  to the row it replaced. The old row is kept (status "reassigned"), not edited.

Additive; inert unless an assignment uses instructor_assigned or an instructor
reassigns a review.

Revision ID: 20260926_0015
Revises: 20260921_0014
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_0015"
down_revision: Union[str, None] = "20260921_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_pairings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_id", sa.String(), nullable=False),
        sa.Column("author_user_id", sa.String(), nullable=False),
        sa.Column("reviewer_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["group_challenges.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "author_user_id", name="uq_review_pairing_author"),
    )
    op.create_index("ix_review_pairings_group_id", "review_pairings", ["group_id"])

    op.add_column("verification_assignments",
                  sa.Column("replaces_assignment_id", sa.String(), nullable=True))
    op.create_foreign_key("fk_verif_assign_replaces", "verification_assignments",
                          "verification_assignments", ["replaces_assignment_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_verif_assign_replaces", "verification_assignments", type_="foreignkey")
    op.drop_column("verification_assignments", "replaces_assignment_id")
    op.drop_index("ix_review_pairings_group_id", table_name="review_pairings")
    op.drop_table("review_pairings")
