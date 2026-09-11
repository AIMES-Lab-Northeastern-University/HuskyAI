"""Team-level study arm on group sessions.

Adds `group_sessions.arm` ('control' | 'treatment'), the study condition a team
runs under. Stored per session but drawn per TEAM: the first session a team
creates takes a stratified draw, and every later session of that team copies it
(see _assign_study_arm in main.py). An independent draw per session would put
the same team in control for session 1 and treatment for session 2, which is not
a team-level intervention at all.

Nullable on purpose. Sessions created before this column existed have no arm,
and back-filling them with a draw would invent a condition that never applied to
those teams -- a fabricated assignment is worse for the analysis than a missing
one, which can simply be excluded. No server_default for the same reason: a
default would silently make every pre-existing session look like a real control.

Indexed because the research queries group by it.

As with 0007/0008/0009: nothing runs `alembic upgrade` at deploy (nixpacks starts
bare uvicorn), so init_db's defensive ALTER block is what actually reaches
production. This column genuinely needs that path -- create_all will not alter
the already-populated group_sessions table.

Revision ID: 20260911_0010
Revises: 20260911_0009
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0010"
down_revision: Union[str, None] = "20260911_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "group_sessions",
        sa.Column("arm", sa.String(length=16), nullable=True),
    )
    op.create_index("ix_group_sessions_arm", "group_sessions", ["arm"])


def downgrade() -> None:
    op.drop_index("ix_group_sessions_arm", table_name="group_sessions")
    op.drop_column("group_sessions", "arm")
