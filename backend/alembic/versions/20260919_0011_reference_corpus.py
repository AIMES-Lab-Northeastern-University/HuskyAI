"""Add reference_corpora + corpus_documents, ClassroomChallenge.reference_corpus_id,
EvalResult.grounding.

Per-assignment ground truth the evaluator scores against. Scoped to a
ClassroomChallenge, so the same challenge can carry different corpora in
different sections — which is what makes a corpus an experimental variable
rather than a property of the task.

Additive and default-off: with no corpus attached the evaluator takes an
identical code path and `grounding` stays NULL.

Revision ID: 20260919_0011
Revises: 20260919_0010
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0011"
down_revision: Union[str, None] = "20260919_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reference_corpora",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("classroom_challenge_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("openai_vector_store_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="building"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["classroom_challenge_id"], ["classroom_challenges.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reference_corpora_cc", "reference_corpora", ["classroom_challenge_id"])
    op.create_index("ix_reference_corpora_creator", "reference_corpora", ["created_by_user_id"])

    op.create_table(
        "corpus_documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("corpus_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("openai_file_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("uploaded_by_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["corpus_id"], ["reference_corpora.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_corpus_documents_corpus", "corpus_documents", ["corpus_id"])
    op.create_index("ix_corpus_documents_uploader", "corpus_documents", ["uploaded_by_user_id"])

    op.add_column("classroom_challenges", sa.Column("reference_corpus_id", sa.String(), nullable=True))
    op.add_column("eval_results", sa.Column("grounding", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_results", "grounding")
    op.drop_column("classroom_challenges", "reference_corpus_id")
    op.drop_index("ix_corpus_documents_uploader", table_name="corpus_documents")
    op.drop_index("ix_corpus_documents_corpus", table_name="corpus_documents")
    op.drop_table("corpus_documents")
    op.drop_index("ix_reference_corpora_creator", table_name="reference_corpora")
    op.drop_index("ix_reference_corpora_cc", table_name="reference_corpora")
    op.drop_table("reference_corpora")
