"""Study configuration on ClassroomChallenge + EvalResult.is_graded_revision.

Makes the experimental arm and coach prominence per-assignment settings rather
than hardcoded product choices, so the same challenge can run as the control in
one section and the collaborative arm in another.

Every default reproduces today's behaviour exactly: deploying this enrolls no
existing section into any arm.

Revision ID: 20260919_0010
Revises: 20260919_0009
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0010"
down_revision: Union[str, None] = "20260919_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("classroom_challenges", sa.Column(
        "study_arm", sa.String(length=32), nullable=False, server_default="control_solo_feed"))
    op.add_column("classroom_challenges", sa.Column(
        "coach_prominence", sa.String(length=16), nullable=False, server_default="on_request"))
    op.add_column("classroom_challenges", sa.Column(
        "revision_policy", sa.JSON(), nullable=True))
    op.add_column("classroom_challenges", sa.Column(
        "verification_policy", sa.String(length=32), nullable=False, server_default="none"))
    op.add_column("eval_results", sa.Column(
        "is_graded_revision", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("eval_results", "is_graded_revision")
    op.drop_column("classroom_challenges", "verification_policy")
    op.drop_column("classroom_challenges", "revision_policy")
    op.drop_column("classroom_challenges", "coach_prominence")
    op.drop_column("classroom_challenges", "study_arm")
