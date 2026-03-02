"""Add ag_ui_events table for AG-UI event-sourcing persistence

Revision ID: c3d7e9f12345
Revises: a1c3f2e8d549
Create Date: 2026-03-03 00:00:00.000000

Adds an append-only event log that stores every raw AG-UI event emitted
during a conversation run.  Replaying these rows in sequence order lets
CopilotKit reconstruct the full chat UI state via runtime.replayEvents().

Table: ag_ui_events
  id               BIGINT PK autoincrement
  conversation_id  BIGINT FK → conversations.id  (CASCADE DELETE)
  sequence         INTEGER    monotone counter per conversation
  event            JSONB      full serialised AG-UI event
  created_at       TIMESTAMPTZ server-default now()
  updated_at       TIMESTAMPTZ server-default now()
  UNIQUE (conversation_id, sequence)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3d7e9f12345"
down_revision: Union[str, Sequence[str], None] = "a1c3f2e8d549"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ag_ui_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "event",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_ag_ui_events_conv_seq",
        ),
    )
    op.create_index(
        op.f("ix_ag_ui_events_conversation_id"),
        "ag_ui_events",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ag_ui_events_conversation_id"),
        table_name="ag_ui_events",
    )
    op.drop_table("ag_ui_events")
