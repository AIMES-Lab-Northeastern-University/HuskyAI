"""Create all HuskyAI tables (ORM sync with database.py).

Revision ID: 20260405_0001
Revises:
Create Date: 2026-04-05

Greenfield Supabase/Postgres: run `alembic upgrade head` with DATABASE_URL set.
For local SQLite, `init_db()` on app startup is usually enough instead.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260405_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from database import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from database import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
