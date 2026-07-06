"""
Tests for Alembic migration health.
"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect


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
