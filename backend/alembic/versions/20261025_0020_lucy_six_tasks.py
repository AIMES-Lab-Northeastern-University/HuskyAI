"""Lucy's six-task design: enrollment numbers, two-page answers, exposure judge.

- study_participants.enroll_seq (nullable, unique): the enrollment number that
  picks a participant's cell (condition x set order x error order). Unique, so
  two concurrent enrollments can never take the same number.
- study_task_answers: page 2 of the end-of-task questions is now its own
  submit, so `confidence` becomes nullable, and ai_trust, self_check (post-test
  only, 1-6) and rated_at are added.
- study_exposure_judgments: the model's first-pass EXPOSED_Tk for each
  post-test task.

Study tables only; inert unless STUDY_MODE_ENABLED is set. Not yet run against
production.

Revision ID: 20261025_0020
Revises: 20261023_0019
Create Date: 2026-10-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_0020"
down_revision: Union[str, None] = "20261023_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("study_participants") as batch:
        batch.add_column(sa.Column("enroll_seq", sa.Integer(), nullable=True))
        batch.create_unique_constraint("uq_study_participant_enroll_seq", ["enroll_seq"])

    with op.batch_alter_table("study_task_answers") as batch:
        batch.alter_column("confidence", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("ai_trust", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("self_check", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rated_at", sa.DateTime(), nullable=True))
        batch.create_check_constraint("ck_study_task_answer_trust",
                                      "ai_trust >= 1 AND ai_trust <= 6")
        batch.create_check_constraint("ck_study_task_answer_check",
                                      "self_check >= 1 AND self_check <= 6")

    op.create_table(
        "study_exposure_judgments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("participant_id", sa.String(), sa.ForeignKey("study_participants.id"),
                  nullable=False),
        sa.Column("task", sa.Integer(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("error_type", sa.String(length=16), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("exposed", sa.Boolean(), nullable=True),
        sa.Column("exposure_case", sa.String(length=32), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("judge_version", sa.String(length=32), nullable=False),
        sa.Column("judged_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("participant_id", "task", name="uq_study_exposure_judgment"),
    )
    op.create_index("ix_study_exposure_judgments_participant_id", "study_exposure_judgments",
                    ["participant_id"])


def downgrade() -> None:
    op.drop_index("ix_study_exposure_judgments_participant_id",
                  table_name="study_exposure_judgments")
    op.drop_table("study_exposure_judgments")
    with op.batch_alter_table("study_task_answers") as batch:
        batch.drop_constraint("ck_study_task_answer_check", type_="check")
        batch.drop_constraint("ck_study_task_answer_trust", type_="check")
        batch.drop_column("rated_at")
        batch.drop_column("self_check")
        batch.drop_column("ai_trust")
        batch.alter_column("confidence", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("study_participants") as batch:
        batch.drop_constraint("uq_study_participant_enroll_seq", type_="unique")
        batch.drop_column("enroll_seq")
