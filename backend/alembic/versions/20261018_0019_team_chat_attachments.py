"""Add group_chat_attachments: files shared in the team backchannel.

A new table, so init_db's create_all would also make it; the migration keeps
Alembic's history in step with the models.

Revision ID: 20261018_0019
Revises: 20261003_0018
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261018_0019"
down_revision: Union[str, None] = "20261003_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_chat_attachments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("message_id", sa.String(), sa.ForeignKey("group_chat_messages.id"), nullable=False),
        sa.Column("group_id", sa.String(), sa.ForeignKey("group_challenges.id"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_group_chat_attachments_message_id", "group_chat_attachments", ["message_id"])
    op.create_index("ix_group_chat_attachments_group_id", "group_chat_attachments", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_group_chat_attachments_group_id", table_name="group_chat_attachments")
    op.drop_index("ix_group_chat_attachments_message_id", table_name="group_chat_attachments")
    op.drop_table("group_chat_attachments")
