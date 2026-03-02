"""Drop chat_sessions – flatten session fields into conversations

Revision ID: a1c3f2e8d549
Revises: b9e32f811caa
Create Date: 2026-03-02 12:00:00.000000

chat_sessions was a 1-to-1 wrapper around conversations with no extra
semantic value. This migration:
  1. Adds session fields (session_id, status, message_count, completed_at,
     extra_metadata) directly onto conversations.
  2. Re-points chat_messages.conversation_id (BigInt FK → conversations.id)
     replacing the old session_id (String FK → chat_sessions.session_id).
  3. Drops chat_sessions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1c3f2e8d549"
down_revision: Union[str, Sequence[str], None] = "b9e32f811caa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = "7dfd873465b6"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add session-level columns to conversations
    # ------------------------------------------------------------------
    op.add_column(
        "conversations",
        sa.Column("session_id", sa.String(length=36), nullable=True),  # temp nullable
    )
    op.add_column(
        "conversations",
        sa.Column(
            "status",
            sa.Enum("active", "completed", "archived", name="session_status"),
            nullable=True,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("message_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # Back-fill with placeholder values for any existing rows
    op.execute(
        "UPDATE conversations SET session_id = gen_random_uuid()::text, "
        "status = 'archived', message_count = 0 "
        "WHERE session_id IS NULL"
    )

    # Now tighten the constraints
    op.alter_column("conversations", "session_id", nullable=False)
    op.alter_column("conversations", "status", nullable=False)
    op.alter_column("conversations", "message_count", nullable=False)

    op.create_index(
        op.f("ix_conversations_session_id"),
        "conversations",
        ["session_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 2. Replace chat_messages.session_id with conversation_id
    # ------------------------------------------------------------------

    # Drop the old FK constraint (PostgreSQL auto-names it)
    op.drop_constraint(
        "chat_messages_session_id_fkey", "chat_messages", type_="foreignkey"
    )
    op.drop_index(op.f("ix_chat_messages_session_id"), table_name="chat_messages")
    op.drop_column("chat_messages", "session_id")

    # Add conversation_id column
    op.add_column(
        "chat_messages",
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),  # temp nullable
    )
    # Back-fill for any existing messages (set to a dummy value; data is dev data)
    op.execute(
        "UPDATE chat_messages SET conversation_id = "
        "(SELECT id FROM conversations ORDER BY id LIMIT 1) "
        "WHERE conversation_id IS NULL"
    )
    op.alter_column("chat_messages", "conversation_id", nullable=False)

    op.create_index(
        op.f("ix_chat_messages_conversation_id"),
        "chat_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_foreign_key(
        "chat_messages_conversation_id_fkey",
        "chat_messages",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 3. Drop chat_sessions (and its indexes / FK constraints)
    # ------------------------------------------------------------------
    op.drop_index(op.f("ix_chat_sessions_conversation_id"), table_name="chat_sessions")
    op.drop_index(op.f("ix_chat_sessions_session_id"), table_name="chat_sessions")
    op.drop_table("chat_sessions")


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Recreate chat_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "completed", "archived", name="session_status"),
            nullable=False,
        ),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_sessions_session_id"), "chat_sessions", ["session_id"], unique=True
    )
    op.create_index(
        op.f("ix_chat_sessions_conversation_id"),
        "chat_sessions",
        ["conversation_id"],
        unique=False,
    )

    # Restore chat_messages.session_id
    op.drop_constraint(
        "chat_messages_conversation_id_fkey", "chat_messages", type_="foreignkey"
    )
    op.drop_index(op.f("ix_chat_messages_conversation_id"), table_name="chat_messages")
    op.drop_column("chat_messages", "conversation_id")

    op.add_column(
        "chat_messages",
        sa.Column("session_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False
    )
    op.create_foreign_key(
        "chat_messages_session_id_fkey",
        "chat_messages",
        "chat_sessions",
        ["session_id"],
        ["session_id"],
        ondelete="CASCADE",
    )

    # Remove columns added to conversations
    op.drop_index(op.f("ix_conversations_session_id"), table_name="conversations")
    op.drop_column("conversations", "extra_metadata")
    op.drop_column("conversations", "completed_at")
    op.drop_column("conversations", "message_count")
    op.drop_column("conversations", "status")
    op.drop_column("conversations", "session_id")
