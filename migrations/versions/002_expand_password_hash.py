"""expand password_hash column to 256 chars

Revision ID: 002_expand_password_hash
Revises: 001_initial_schema
Create Date: 2026-04-25 00:00:00.000000

String(128) was too short for Werkzeug's default scrypt hashes (~162 chars).
PostgreSQL enforces VARCHAR length strictly, causing a 500 on user registration.
SQLite ignores the constraint, which is why this only failed in production.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_expand_password_hash"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=128),
        type_=sa.String(length=256),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=256),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
