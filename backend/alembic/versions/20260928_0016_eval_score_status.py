"""Add eval_results.score_status and eval_results.scored_at.

A failed evaluation used to be saved as all-zero scores, indistinguishable from
a genuinely weak turn. It is now saved with NULL scores and score_status
"pending", retried in the background, and filled in later ("scored_late", with
scored_at) or given up on ("failed").

Additive and nullable: every existing row reads as "scored at the time". No
backfill of past zero-score rows (a decision recorded with the change).

Revision ID: 20260928_0016
Revises: 20260926_0015
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0016"
down_revision: Union[str, None] = "20260926_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("eval_results", sa.Column("score_status", sa.String(length=16), nullable=True))
    op.add_column("eval_results", sa.Column("scored_at", sa.DateTime(), nullable=True))
    op.create_index("ix_eval_results_score_status", "eval_results", ["score_status"])


def downgrade() -> None:
    op.drop_index("ix_eval_results_score_status", table_name="eval_results")
    op.drop_column("eval_results", "scored_at")
    op.drop_column("eval_results", "score_status")
