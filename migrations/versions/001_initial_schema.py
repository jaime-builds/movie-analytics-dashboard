"""initial schema baseline

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-04-24 00:00:00.000000

Baseline migration capturing the full schema as it exists at project start.
All tables already exist in the database; this migration is marked as the
starting point so future schema changes can be tracked with Alembic.

To stamp an existing database without running the DDL:
    alembic stamp 001_initial_schema
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- genres -----------------------------------------------------------
    op.create_table(
        "genres",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_id"),
    )

    # --- people -----------------------------------------------------------
    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("profile_path", sa.String(length=255), nullable=True),
        sa.Column("popularity", sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_id"),
    )

    # --- production_companies ---------------------------------------------
    op.create_table(
        "production_companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("logo_path", sa.String(length=255), nullable=True),
        sa.Column("origin_country", sa.String(length=10), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_id"),
    )

    # --- users ------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    # --- movies -----------------------------------------------------------
    op.create_table(
        "movies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("original_title", sa.String(length=255), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("budget", sa.BigInteger(), nullable=True),
        sa.Column("revenue", sa.BigInteger(), nullable=True),
        sa.Column("popularity", sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column("vote_average", sa.DECIMAL(precision=3, scale=1), nullable=True),
        sa.Column("vote_count", sa.Integer(), nullable=True),
        sa.Column("poster_path", sa.String(length=255), nullable=True),
        sa.Column("backdrop_path", sa.String(length=255), nullable=True),
        sa.Column("imdb_id", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_id"),
    )
    op.create_index("idx_movies_vote_count", "movies", ["vote_count"])
    op.create_index("idx_movies_title", "movies", ["title"])

    # --- movie_genres (association) ---------------------------------------
    op.create_table(
        "movie_genres",
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("genre_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.PrimaryKeyConstraint("movie_id", "genre_id"),
    )
    op.create_index("idx_movie_genres_genre_id", "movie_genres", ["genre_id"])

    # --- movie_companies (association) ------------------------------------
    op.create_table(
        "movie_companies",
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["production_companies.id"]),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.PrimaryKeyConstraint("movie_id", "company_id"),
    )

    # --- user_favorites (association) ------------------------------------
    op.create_table(
        "user_favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "movie_id"),
    )

    # --- user_watchlist (association) ------------------------------------
    op.create_table(
        "user_watchlist",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "movie_id"),
    )

    # --- cast -------------------------------------------------------------
    op.create_table(
        "cast",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("character_name", sa.String(length=255), nullable=True),
        sa.Column("cast_order", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- crew -------------------------------------------------------------
    op.create_table(
        "crew",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("job", sa.String(length=100), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_crew_person_id", "crew", ["person_id"])
    op.create_index("idx_crew_person_job", "crew", ["person_id", "job"])

    # --- ratings ----------------------------------------------------------
    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="check_rating_range"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_movie_rating", "ratings", ["user_id", "movie_id"], unique=True)
    op.create_index("idx_ratings_movie_id", "ratings", ["movie_id"])

    # --- reviews ----------------------------------------------------------
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_movie_reviews", "reviews", ["movie_id"])
    op.create_index("idx_user_reviews", "reviews", ["user_id"])

    # --- collections ------------------------------------------------------
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_collections_user_id", "collections", ["user_id"])

    # --- collection_movies (association) ---------------------------------
    op.create_table(
        "collection_movies",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"]),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.PrimaryKeyConstraint("collection_id", "movie_id"),
    )


def downgrade() -> None:
    op.drop_table("collection_movies")
    op.drop_index("idx_collections_user_id", table_name="collections")
    op.drop_table("collections")
    op.drop_index("idx_user_reviews", table_name="reviews")
    op.drop_index("idx_movie_reviews", table_name="reviews")
    op.drop_table("reviews")
    op.drop_index("idx_ratings_movie_id", table_name="ratings")
    op.drop_index("idx_user_movie_rating", table_name="ratings")
    op.drop_table("ratings")
    op.drop_index("idx_crew_person_job", table_name="crew")
    op.drop_index("idx_crew_person_id", table_name="crew")
    op.drop_table("crew")
    op.drop_table("cast")
    op.drop_table("user_watchlist")
    op.drop_table("user_favorites")
    op.drop_table("movie_companies")
    op.drop_index("idx_movie_genres_genre_id", table_name="movie_genres")
    op.drop_table("movie_genres")
    op.drop_index("idx_movies_title", table_name="movies")
    op.drop_index("idx_movies_vote_count", table_name="movies")
    op.drop_table("movies")
    op.drop_table("users")
    op.drop_table("production_companies")
    op.drop_table("people")
    op.drop_table("genres")
