"""Snapshot research consent on artifact_revisions, verification_responses,
contested_responses.

A standing constraint of the study design: consent is captured per row at write
time, so the export filter is immune to a later toggle. EvalResult and
StudyEvent already did this; these three tables were added without it, which
would have left the export unable to filter them except by guessing from the
user's current setting.

Existing rows default to false — the conservative direction. A row whose
consent was never captured must not be exported on an assumption.

Revision ID: 20260921_0014
Revises: 20260919_0013
Create Date: 2026-09-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0014"
down_revision: Union[str, None] = "20260919_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("artifact_revisions", "verification_responses", "contested_responses")


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("consent_research", sa.Boolean(),
                                   nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for t in _TABLES:
        op.drop_column(t, "consent_research")
