"""add added_at timestamp to collection movies

Revision ID: 004_add_collection_movies_added_at
Revises: 003_add_query_indexes_review_unique
Create Date: 2026-07-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_add_collection_movies_added_at"
down_revision: Union[str, None] = "003_add_query_indexes_review_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("collection_movies") as batch_op:
        batch_op.add_column(sa.Column("added_at", sa.DateTime(), nullable=True))

    op.execute(
        sa.text("UPDATE collection_movies SET added_at = CURRENT_TIMESTAMP WHERE added_at IS NULL")
    )

    with op.batch_alter_table("collection_movies") as batch_op:
        batch_op.alter_column(
            "added_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("collection_movies") as batch_op:
        batch_op.drop_column("added_at")
