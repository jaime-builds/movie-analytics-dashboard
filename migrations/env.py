"""
Alembic environment configuration.

Imports the project's SQLAlchemy Base and Config so migrations are always
generated from the real model definitions and connect to the right database.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# ---------------------------------------------------------------------------
# Make sure the repo root is on the path so we can import src and config
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.config import Config  # noqa: E402
from src.models import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object (gives access to values in alembic.ini)
# ---------------------------------------------------------------------------
config = context.config

# Inject the real database URL from our Config class, overriding the blank
# sqlalchemy.url in alembic.ini. The ini parser treats % as interpolation, so a
# percent-encoded password (for example %40) must be escaped as %%.
config.set_main_option("sqlalchemy.url", Config.DATABASE_URL.replace("%", "%%"))

# Width of alembic_version.version_num. Alembic's default is VARCHAR(32), but
# revision IDs here are descriptive and two already exceed 32 characters.
VERSION_NUM_LENGTH = 255

# Set up Python logging from the alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that Alembic compares against when autogenerating.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline mode: emit SQL to stdout without a live DB connection
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _ensure_wide_version_table(connection) -> None:
    """Create or widen alembic_version.version_num before any migration runs.

    On Postgres a revision ID longer than the column fails the whole upgrade,
    and because the upgrade runs in one transaction, a fresh database ends up
    empty (the 2026-07-29 incident). SQLite doesn't enforce VARCHAR lengths.
    """
    if connection.dialect.name != "postgresql":
        return

    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            f"version_num VARCHAR({VERSION_NUM_LENGTH}) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    current_length = connection.execute(
        text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'alembic_version' "
            "AND column_name = 'version_num'"
        )
    ).scalar()
    if current_length is not None and current_length < VERSION_NUM_LENGTH:
        connection.execute(
            text(
                "ALTER TABLE alembic_version ALTER COLUMN version_num "
                f"TYPE VARCHAR({VERSION_NUM_LENGTH})"
            )
        )
    connection.commit()


# ---------------------------------------------------------------------------
# Online mode: run migrations against a live DB connection
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _ensure_wide_version_table(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
