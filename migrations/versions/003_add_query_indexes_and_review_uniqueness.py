"""add query indexes and unique review constraint

Revision ID: 003_add_query_indexes_review_unique
Revises: 002_expand_password_hash
Create Date: 2026-07-05 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_add_query_indexes_review_unique"
down_revision: Union[str, None] = "002_expand_password_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _duplicate_review_pairs() -> list[tuple[int, int, int]]:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT user_id, movie_id, COUNT(*) AS duplicate_count
            FROM reviews
            GROUP BY user_id, movie_id
            HAVING COUNT(*) > 1
            ORDER BY duplicate_count DESC, user_id, movie_id
            """
        )
    ).fetchall()
    return [(row.user_id, row.movie_id, row.duplicate_count) for row in rows]


def upgrade() -> None:
    duplicate_pairs = _duplicate_review_pairs()
    if duplicate_pairs:
        sample = ", ".join(
            f"user_id={user_id}/movie_id={movie_id}/count={count}"
            for user_id, movie_id, count in duplicate_pairs[:5]
        )
        raise RuntimeError(
            f"Cannot add uq_reviews_user_movie while duplicate reviews exist: {sample}"
        )

    op.create_index("idx_cast_movie_id", "cast", ["movie_id"])
    op.create_index("idx_cast_person_id", "cast", ["person_id"])
    op.create_index("idx_crew_movie_id", "crew", ["movie_id"])
    op.create_index(
        "idx_movie_companies_company_id",
        "movie_companies",
        ["company_id"],
    )
    op.create_index("idx_movies_release_date", "movies", ["release_date"])
    op.create_index("idx_movies_vote_average", "movies", ["vote_average"])
    op.create_index("idx_movies_popularity", "movies", ["popularity"])

    with op.batch_alter_table("reviews") as batch_op:
        batch_op.create_unique_constraint(
            "uq_reviews_user_movie",
            ["user_id", "movie_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_constraint("uq_reviews_user_movie", type_="unique")

    op.drop_index("idx_movies_popularity", table_name="movies")
    op.drop_index("idx_movies_vote_average", table_name="movies")
    op.drop_index("idx_movies_release_date", table_name="movies")
    op.drop_index("idx_movie_companies_company_id", table_name="movie_companies")
    op.drop_index("idx_crew_movie_id", table_name="crew")
    op.drop_index("idx_cast_person_id", table_name="cast")
    op.drop_index("idx_cast_movie_id", table_name="cast")
