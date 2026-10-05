"""Merge the team-chat-logging/research-notice branch with eval score status.

Both 20260927_0016 and 20260928_0016 descend from 20260926_0015, which left two
heads. No schema change; this only rejoins the history so `alembic upgrade head`
works on any database regardless of which side it was migrated along.

Revision ID: 20261003_0018
Revises: 20260927_0017, 20260928_0016
Create Date: 2026-10-03
"""

from typing import Sequence, Union

revision: str = "20261003_0018"
down_revision: Union[str, Sequence[str], None] = ("20260927_0017", "20260928_0016")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
