"""Add classroom_challenges.team_chat_logging.

Whether the team backchannel enters the research record: off | metadata |
content. Defaults to "off", which is today's behaviour — messages are stored for
replay but no study event is emitted — so no section starts logging team chat
by deploying this. The PI decides the value (docs/collab-study-pending.md #3).

Revision ID: 20260927_0016
Revises: 20260926_0015
Create Date: 2026-09-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0016"
down_revision: Union[str, None] = "20260926_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("classroom_challenges",
                  sa.Column("team_chat_logging", sa.String(16), nullable=False,
                            server_default="off"))


def downgrade() -> None:
    op.drop_column("classroom_challenges", "team_chat_logging")
