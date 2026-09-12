"""Document-citation retrieval (v1).

Adds the columns needed to index uploaded chat attachments (PDF/docx/text) into
a per-conversation OpenAI vector store, so the chat turn loop can surface
"related passages" alongside an assistant answer:
- conversations.openai_vector_store_id: the conversation's OpenAI vector store,
  created lazily on the first indexable attachment.
- attachments.openai_file_id / index_status: per-attachment indexing state.

All nullable — no behavior change for existing rows until a new attachment is
uploaded through the updated chat flow.

Revision ID: 20260815_0006
Revises: 20260621_0005
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0006"
down_revision: Union[str, None] = "20260621_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("openai_vector_store_id", sa.String(), nullable=True))
    op.add_column("attachments", sa.Column("openai_file_id", sa.String(), nullable=True))
    op.add_column("attachments", sa.Column("index_status", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "index_status")
    op.drop_column("attachments", "openai_file_id")
    op.drop_column("conversations", "openai_vector_store_id")
