"""Add city_id to conversations and default_city_id to users

Revision ID: e2f3a4b5c6d7
Revises: c3d7e9f12345
Create Date: 2026-03-06 00:00:00.000000

Adds:
  conversations.city_id         VARCHAR(50) NOT NULL DEFAULT 'lucknow'
  users.default_city_id         VARCHAR(50) NOT NULL DEFAULT 'lucknow'
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "c3d7e9f12345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # conversations.city_id
    op.add_column(
        "conversations",
        sa.Column(
            "city_id",
            sa.String(length=50),
            nullable=False,
            server_default="lucknow",
        ),
    )
    op.create_index(
        op.f("ix_conversations_city_id"),
        "conversations",
        ["city_id"],
        unique=False,
    )

    # users.default_city_id
    op.add_column(
        "users",
        sa.Column(
            "default_city_id",
            sa.String(length=50),
            nullable=False,
            server_default="lucknow",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "default_city_id")
    op.drop_index(op.f("ix_conversations_city_id"), table_name="conversations")
    op.drop_column("conversations", "city_id")
