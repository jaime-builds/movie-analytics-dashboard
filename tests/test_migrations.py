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


def _upgrade_head(database_url):
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_migrations_007_to_009_add_their_columns(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'later.sqlite').as_posix()}"
    result = _upgrade_head(database_url)
    assert result.returncode == 0, result.stdout + result.stderr

    inspector = inspect(create_engine(database_url))
    columns = {
        table: {c["name"]: c for c in inspector.get_columns(table)}
        for table in ("users", "movies", "user_favorites", "user_watchlist", "cast")
    }
    assert columns["users"]["session_version"]["nullable"] is False
    assert columns["users"]["hide_activity"]["nullable"] is False
    assert columns["movies"]["is_mature"]["nullable"] is False
    assert columns["movies"]["hide_from_featured"]["nullable"] is False
    assert "added_at" in columns["user_favorites"]
    assert "added_at" in columns["user_watchlist"]
    # TEXT has no length limit (VARCHAR(255) overflowed on voice casts)
    assert getattr(columns["cast"]["character_name"]["type"], "length", None) is None

    for table in ("user_favorites", "user_watchlist", "collection_movies", "movie_of_the_day"):
        names = {index["name"] for index in inspector.get_indexes(table)}
        assert f"idx_{table}_movie_id" in names


def test_every_revision_id_fits_the_version_column():
    """env.py widens alembic_version to 255; keep IDs well inside that."""
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory

    repo_root = Path(__file__).resolve().parents[1]
    script = ScriptDirectory.from_config(AlembicConfig(str(repo_root / "alembic.ini")))
    lengths = {rev.revision: len(rev.revision) for rev in script.walk_revisions()}

    assert lengths
    assert max(lengths.values()) <= 64, lengths


@pytest.mark.skipif(
    not os.getenv("MIGRATION_TEST_DATABASE_URL"),
    reason="needs MIGRATION_TEST_DATABASE_URL (an empty Postgres database; set in CI)",
)
def test_alembic_upgrade_head_on_a_fresh_postgres_database():
    """The 2026-07-29 failure: revision 003 overflowed VARCHAR(32) on Postgres."""
    database_url = os.environ["MIGRATION_TEST_DATABASE_URL"]
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    result = _upgrade_head(database_url)
    assert result.returncode == 0, result.stdout + result.stderr

    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        width = connection.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
            )
        ).scalar()
    assert version == "009_content_flags_and_dates"
    assert width == 255

    # Running it again on an up-to-date database is a no-op
    again = _upgrade_head(database_url)
    assert again.returncode == 0, again.stdout + again.stderr
    engine.dispose()
