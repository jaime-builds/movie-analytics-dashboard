"""widen cast.character_name and index association movie_id columns

Revision ID: 008_cast_text_and_fk_indexes
Revises: 007_user_session_version
Create Date: 2026-11-02 00:00:00.000000

* cast.character_name VARCHAR(255) -> TEXT. TMDB joins every role an actor
  voices into one string, and ensemble voice casts run past 255 characters.
  Postgres rejected those rows during the sync (SQLite never enforced it).
  VARCHAR -> TEXT is a metadata-only change on Postgres.
* Indexes on movie_id for user_favorites, user_watchlist, collection_movies
  and movie_of_the_day. Their primary keys lead with the other column, so
  lookups and deletes by movie had no index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_cast_text_and_fk_indexes"
down_revision: Union[str, None] = "007_user_session_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MOVIE_ID_INDEXES = {
    "idx_user_favorites_movie_id": "user_favorites",
    "idx_user_watchlist_movie_id": "user_watchlist",
    "idx_collection_movies_movie_id": "collection_movies",
    "idx_movie_of_the_day_movie_id": "movie_of_the_day",
}


def upgrade() -> None:
    with op.batch_alter_table("cast") as batch_op:
        batch_op.alter_column(
            "character_name",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=True,
        )

    for index_name, table_name in _MOVIE_ID_INDEXES.items():
        op.create_index(index_name, table_name, ["movie_id"])


def downgrade() -> None:
    for index_name, table_name in _MOVIE_ID_INDEXES.items():
        op.drop_index(index_name, table_name=table_name)

    # Longer values would not fit back into VARCHAR(255); trim them first
    op.execute(
        'UPDATE "cast" SET character_name = SUBSTR(character_name, 1, 255) '
        "WHERE LENGTH(character_name) > 255"
    )
    with op.batch_alter_table("cast") as batch_op:
        batch_op.alter_column(
            "character_name",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=True,
        )
