"""Add classrooms.listed_in_directory for browse UI.

Revision ID: 20260405_0002
Revises: 20260405_0001
Create Date: 2026-04-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260405_0002"
down_revision: Union[str, None] = "20260405_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "classrooms",
        sa.Column(
            "listed_in_directory",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("classrooms", "listed_in_directory")
