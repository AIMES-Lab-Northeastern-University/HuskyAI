"""Add users.research_ack_version.

Which version of the research notice a user acknowledged, so that shipping new
consent wording can re-show the gate to everyone who accepted an older one.
NULL with research_ack_at set is read as version 1 (every acknowledgement before
this column existed was of the original notice). Inert until
RESEARCH_NOTICE_VERSION is raised above 1.

Revision ID: 20260927_0017
Revises: 20260927_0016
Create Date: 2026-09-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0017"
down_revision: Union[str, None] = "20260927_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("research_ack_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "research_ack_version")
