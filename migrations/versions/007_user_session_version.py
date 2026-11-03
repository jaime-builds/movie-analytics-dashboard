"""add users.session_version for revocable sessions

Revision ID: 007_user_session_version
Revises: 006_admin_dashboard
Create Date: 2026-11-02 00:00:00.000000

Logout and ban bump a user's session_version. The session cookie carries the
version it was issued with, and get_current_user rejects a cookie whose
version is older, so a copied cookie stops working once its owner logs out.

Additive NOT NULL column with a server default, so plain ``op.add_column``
works on SQLite and Postgres (same pattern as 006).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_user_session_version"
down_revision: Union[str, None] = "006_admin_dashboard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "session_version")
