"""add movie_of_the_day table

Revision ID: 005_add_movie_of_the_day
Revises: 004_add_collection_movies_added_at
Create Date: 2026-07-21 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_add_movie_of_the_day"
down_revision: Union[str, None] = "004_add_collection_movies_added_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "movie_of_the_day",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("shown_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shown_date", name="uq_movie_of_the_day_shown_date"),
    )


def downgrade() -> None:
    op.drop_table("movie_of_the_day")
