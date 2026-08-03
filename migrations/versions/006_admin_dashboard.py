"""add admin dashboard tables and moderation columns

Revision ID: 006_admin_dashboard
Revises: 005_add_movie_of_the_day
Create Date: 2026-08-03 00:00:00.000000

Adds the schema behind the admin dashboard:
  * users.is_admin / is_banned / banned_at   -- access control
  * ratings/reviews.is_deleted / deleted_at  -- soft-delete moderation
  * page_views                               -- per-path daily view counters
  * site_settings                            -- key/value site toggles

All column additions are purely additive (nullable, or NOT NULL with a
server default), so plain ``op.add_column`` works on SQLite as well as
Postgres. batch_alter_table is deliberately avoided here: rebuilding the
``ratings`` table would risk dropping the ``check_rating_range`` CHECK
constraint that SQLite cannot always round-trip through reflection.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_admin_dashboard"
down_revision: Union[str, None] = "005_add_movie_of_the_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users: admin flag + ban state ------------------------------------
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("banned_at", sa.DateTime(), nullable=True))

    # --- ratings / reviews: soft-delete moderation ------------------------
    for table_name in ("ratings", "reviews"):
        op.add_column(
            table_name,
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.add_column(table_name, sa.Column("deleted_at", sa.DateTime(), nullable=True))

    # --- page_views: one counter row per (path, day) ----------------------
    op.create_table(
        "page_views",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("view_date", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", "view_date", name="uq_page_views_path_date"),
    )
    op.create_index("idx_page_views_view_date", "page_views", ["view_date"])

    # --- site_settings: key/value toggles ---------------------------------
    site_settings = op.create_table(
        "site_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.bulk_insert(site_settings, [{"key": "registration_enabled", "value": "true"}])


def downgrade() -> None:
    op.drop_table("site_settings")
    op.drop_index("idx_page_views_view_date", table_name="page_views")
    op.drop_table("page_views")

    for table_name in ("reviews", "ratings"):
        op.drop_column(table_name, "deleted_at")
        op.drop_column(table_name, "is_deleted")

    op.drop_column("users", "banned_at")
    op.drop_column("users", "is_banned")
    op.drop_column("users", "is_admin")
