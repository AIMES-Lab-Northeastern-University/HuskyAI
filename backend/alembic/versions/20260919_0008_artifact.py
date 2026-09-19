"""Add the shared artifact: artifacts, artifact_sections, artifact_revisions.

One artifact per group session. Content lives in sections, which are the unit of
both write conflict (optimistic concurrency via `version`) and read granularity.
An assignment that defines no sections gets a single implicit one, so the model
degrades to a free-form document without a separate code path.

artifact_revisions is append-only research history, never pruned.

Purely additive.

Revision ID: 20260919_0008
Revises: 20260919_0007
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0008"
down_revision: Union[str, None] = "20260919_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_session_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["group_session_id"], ["group_sessions.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_session_id", name="uq_artifact_group_session"),
    )
    op.create_index("ix_artifacts_group_session_id", "artifacts", ["group_session_id"])

    op.create_table(
        "artifact_sections",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_user_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "key", name="uq_artifact_section_key"),
    )
    op.create_index("ix_artifact_sections_artifact_id", "artifact_sections", ["artifact_id"])

    op.create_table(
        "artifact_revisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("section_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author_user_id", sa.String(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("bytes_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["artifact_sections.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", "version", name="uq_artifact_revision_version"),
    )
    op.create_index("ix_artifact_revisions_artifact_id", "artifact_revisions", ["artifact_id"])
    op.create_index("ix_artifact_revisions_section_id", "artifact_revisions", ["section_id"])
    op.create_index("ix_artifact_revisions_author_user_id", "artifact_revisions", ["author_user_id"])


def downgrade() -> None:
    op.drop_index("ix_artifact_revisions_author_user_id", table_name="artifact_revisions")
    op.drop_index("ix_artifact_revisions_section_id", table_name="artifact_revisions")
    op.drop_index("ix_artifact_revisions_artifact_id", table_name="artifact_revisions")
    op.drop_table("artifact_revisions")
    op.drop_index("ix_artifact_sections_artifact_id", table_name="artifact_sections")
    op.drop_table("artifact_sections")
    op.drop_index("ix_artifacts_group_session_id", table_name="artifacts")
    op.drop_table("artifacts")
