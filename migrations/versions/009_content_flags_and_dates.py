"""add content flags, list dates and the activity opt-out

Revision ID: 009_content_flags_and_dates
Revises: 008_cast_text_and_fk_indexes
Create Date: 2026-11-02 00:00:00.000000

* movies.is_mature -- set by the sync (and scripts/backfill_mature_flags.py)
  when a movie carries one of the mature TMDB keywords in src/content.py.
  Mature movies never appear on the home page or as Movie of the Day, and
  the family-friendly toggle hides them elsewhere.
* movies.hide_from_featured -- an admin's manual "keep off the home page".
* user_favorites.added_at / user_watchlist.added_at -- when a movie was added,
  for Year in Review and the activity feed. Existing rows stay NULL: the add
  date was never recorded.
* users.hide_activity -- opt out of the public activity feed.

All additive (nullable, or NOT NULL with a server default), so plain
add_column works on SQLite and Postgres, as in 006.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_content_flags_and_dates"
down_revision: Union[str, None] = "008_cast_text_and_fk_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movies",
        sa.Column("is_mature", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "movies",
        sa.Column("hide_from_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("user_favorites", sa.Column("added_at", sa.DateTime(), nullable=True))
    op.add_column("user_watchlist", sa.Column("added_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column("hide_activity", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "hide_activity")
    op.drop_column("user_watchlist", "added_at")
    op.drop_column("user_favorites", "added_at")
    op.drop_column("movies", "hide_from_featured")
    op.drop_column("movies", "is_mature")
