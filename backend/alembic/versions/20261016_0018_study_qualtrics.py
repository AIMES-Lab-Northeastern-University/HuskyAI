"""Add study_enrollments and study_participant_status.

Qualtrics integration for study mode: an enrollment links a participant to the
survey's ResponseID (and holds the encrypted sign-in code, so enrollment is
idempotent); the status row records the session window (first sign-in) and
revocation / expiry.

New tables only; no existing table is altered. Inert unless STUDY_MODE_ENABLED
is set.

Revision ID: 20261016_0018
Revises: 20261010_0017
Create Date: 2026-10-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_0018"
down_revision: Union[str, None] = "20261010_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_enrollments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("participant_id", sa.String(), sa.ForeignKey("study_participants.id"),
                  nullable=False),
        sa.Column("response_id", sa.String(length=64), nullable=False),
        sa.Column("code_ciphertext", sa.Text(), nullable=False),
        sa.Column("consent_recorded_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("response_id", name="uq_study_enrollment_response"),
        sa.UniqueConstraint("participant_id", name="uq_study_enrollment_participant"),
    )
    op.create_table(
        "study_participant_status",
        sa.Column("participant_id", sa.String(), sa.ForeignKey("study_participants.id"),
                  nullable=False),
        sa.Column("first_login_at", sa.DateTime(), nullable=True),
        sa.Column("expired_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("participant_id"),
    )


def downgrade() -> None:
    op.drop_table("study_participant_status")
    op.drop_table("study_enrollments")
