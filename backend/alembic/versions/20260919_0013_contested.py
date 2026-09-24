"""Add contested_pairs + contested_responses (Phase 4).

Surfaces a teammate contribution and a coach output that diverge on the same
subproblem, and records which the student adopts and whether they checked
either. The subproblem is the artifact section key, which is what unblocked
this phase without inventing a second decomposition.

Inspection flags are derived from read events, never self-reported.

Additive; nothing surfaces unless an instructor scripts a pair.

Revision ID: 20260919_0013
Revises: 20260919_0012
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0013"
down_revision: Union[str, None] = "20260919_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contested_pairs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_session_id", sa.String(), nullable=False),
        sa.Column("subproblem_key", sa.String(length=64), nullable=False),
        sa.Column("option_a_revision_id", sa.String(), nullable=True),
        sa.Column("option_a_text", sa.Text(), nullable=False),
        sa.Column("option_b_message_id", sa.String(), nullable=True),
        sa.Column("option_b_text", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="instructor_scripted"),
        sa.Column("better_option", sa.String(length=8), nullable=True),
        sa.Column("surfaced_to_user_id", sa.String(), nullable=False),
        sa.Column("surfaced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_session_id"], ["group_sessions.id"]),
        sa.ForeignKeyConstraint(["option_a_revision_id"], ["artifact_revisions.id"]),
        sa.ForeignKeyConstraint(["option_b_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["surfaced_to_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contested_pairs_session", "contested_pairs", ["group_session_id"])
    op.create_index("ix_contested_pairs_user", "contested_pairs", ["surfaced_to_user_id"])

    op.create_table(
        "contested_responses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("pair_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("adopted", sa.String(length=16), nullable=False),
        sa.Column("inspected_a", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("inspected_b", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dwell_ms_a", sa.Integer(), nullable=True),
        sa.Column("dwell_ms_b", sa.Integer(), nullable=True),
        sa.Column("rationale_text", sa.Text(), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["pair_id"], ["contested_pairs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contested_resp_pair", "contested_responses", ["pair_id"])
    op.create_index("ix_contested_resp_user", "contested_responses", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_contested_resp_user", table_name="contested_responses")
    op.drop_index("ix_contested_resp_pair", table_name="contested_responses")
    op.drop_table("contested_responses")
    op.drop_index("ix_contested_pairs_user", table_name="contested_pairs")
    op.drop_index("ix_contested_pairs_session", table_name="contested_pairs")
    op.drop_table("contested_pairs")
