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
    assert "page_views" in tables
    assert "site_settings" in tables

    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert user_columns["password_hash"]["type"].length == 256
    assert user_columns["is_admin"]["nullable"] is False
    assert user_columns["is_banned"]["nullable"] is False
    assert "banned_at" in user_columns

    for moderated_table in ("ratings", "reviews"):
        moderated_columns = {
            column["name"]: column for column in inspector.get_columns(moderated_table)
        }
        assert moderated_columns["is_deleted"]["nullable"] is False
        assert "deleted_at" in moderated_columns

    page_view_columns = {column["name"]: column for column in inspector.get_columns("page_views")}
    assert page_view_columns["path"]["type"].length == 255
    assert page_view_columns["view_date"]["nullable"] is False
    assert page_view_columns["count"]["nullable"] is False

    page_view_constraints = {
        constraint["name"]: constraint["column_names"]
        for constraint in inspector.get_unique_constraints("page_views")
    }
    assert page_view_constraints["uq_page_views_path_date"] == ["path", "view_date"]

    site_setting_columns = {
        column["name"]: column for column in inspector.get_columns("site_settings")
    }
    assert site_setting_columns["key"]["primary_key"]
    assert "value" in site_setting_columns

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
        "page_views": {"idx_page_views_view_date"},
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
        seeded_settings = dict(
            connection.execute(text("SELECT key, value FROM site_settings")).all()
        )
        assert seeded_settings["registration_enabled"] == "true"

        connection.execute(
            text("INSERT INTO users (id, username, password_hash) VALUES (1, 'u1', 'hash')")
        )

        # The new NOT NULL flags carry server defaults, so plain inserts still work
        new_user_flags = connection.execute(
            text("SELECT is_admin, is_banned, banned_at FROM users WHERE id = 1")
        ).one()
        assert bool(new_user_flags.is_admin) is False
        assert bool(new_user_flags.is_banned) is False
        assert new_user_flags.banned_at is None
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
