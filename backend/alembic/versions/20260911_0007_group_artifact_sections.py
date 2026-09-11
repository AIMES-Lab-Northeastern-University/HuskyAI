"""Shared group artifact, divided into per-subproblem sections.

Adds group_artifact_sections: one row per (group session, section), holding the
section's current content plus who last wrote it. Editing is serialized by a
per-section Redis lock (see backend/group_room.py), not by anything in the
schema -- this table only stores the committed content.

Each session has its own independent artifact. When a team starts a new session,
the previous session's final content is copied in as the starting point, and
carried_from_session_number records where it came from.

NOTE: nothing runs `alembic upgrade` at deploy time (backend/nixpacks.toml starts
bare uvicorn). What actually creates this table in production is init_db's
`Base.metadata.create_all`, which picks up any new table automatically -- the
defensive ALTERs there exist only for columns added to tables that already exist,
so a brand-new table needs no extra handling. This revision exists to keep the
migration history honest, not because it is what runs.

Revision ID: 20260911_0007
Revises: 20260815_0006
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0007"
down_revision: Union[str, None] = "20260815_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_artifact_sections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("group_session_id", sa.String(), sa.ForeignKey("group_sessions.id"), nullable=False),
        sa.Column("section_key", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("carried_from_session_number", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("group_session_id", "section_key", name="uq_artifact_section"),
    )
    op.create_index(
        "ix_group_artifact_sections_group_session_id",
        "group_artifact_sections",
        ["group_session_id"],
    )
    op.create_index(
        "ix_group_artifact_sections_updated_by_user_id",
        "group_artifact_sections",
        ["updated_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_group_artifact_sections_updated_by_user_id", table_name="group_artifact_sections")
    op.drop_index("ix_group_artifact_sections_group_session_id", table_name="group_artifact_sections")
    op.drop_table("group_artifact_sections")
