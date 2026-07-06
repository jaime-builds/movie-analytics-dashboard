"""
Tests for Alembic migration health.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text


def test_alembic_upgrade_head_builds_clean_sqlite_database(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "clean-alembic.sqlite"
    database_url = f"sqlite:///{db_path.as_posix()}"

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr

    engine = create_engine(database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert "alembic_version" in tables
    assert "movies" in tables
    assert "users" in tables
    assert "collections" in tables

    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert user_columns["password_hash"]["type"].length == 256

    collection_movie_columns = {
        column["name"]: column for column in inspector.get_columns("collection_movies")
    }
    assert "added_at" in collection_movie_columns
    assert collection_movie_columns["added_at"]["nullable"] is False

    expected_indexes = {
        "cast": {"idx_cast_movie_id", "idx_cast_person_id"},
        "crew": {"idx_crew_movie_id", "idx_crew_person_id", "idx_crew_person_job"},
        "movie_companies": {"idx_movie_companies_company_id"},
        "movies": {
            "idx_movies_release_date",
            "idx_movies_vote_average",
            "idx_movies_popularity",
        },
    }
    for table_name, index_names in expected_indexes.items():
        actual_index_names = {index["name"] for index in inspector.get_indexes(table_name)}
        assert index_names <= actual_index_names

    review_constraints = {
        constraint["name"]: constraint["column_names"]
        for constraint in inspector.get_unique_constraints("reviews")
    }
    assert review_constraints["uq_reviews_user_movie"] == ["user_id", "movie_id"]

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, username, password_hash) VALUES (1, 'u1', 'hash')")
        )
        connection.execute(text("INSERT INTO movies (id, tmdb_id, title) VALUES (1, 101, 'M1')"))
        connection.execute(
            text(
                "INSERT INTO reviews (user_id, movie_id, content) " "VALUES (1, 1, 'first review')"
            )
        )

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO reviews (user_id, movie_id, content) "
                    "VALUES (1, 1, 'second review')"
                )
            )
