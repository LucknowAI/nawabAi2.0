"""
SQLAlchemy ORM models for conversations and messages.

Tables
------
conversations  – one row per logical conversation belonging to a user.
chat_messages  – one row per message; FK → conversations.id.
"""

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from sqlalchemy_models.base import Base
from src.utils.utils_alembic import column


# ---------------------------------------------------------------------------
# Enums (stored as VARCHAR so they are readable without an enum type in PG)
# ---------------------------------------------------------------------------

MessageRole = Enum("user", "assistant", "system", name="message_role")
ConversationStatus = Enum("active", "completed", "archived", name="session_status")


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

class ConversationModel(Base):
    """A logical conversation (== session) belonging to a single user."""

    __tablename__ = "conversations"

    id = column(BigInteger, primary_key=True, autoincrement=True)

    # FK → users.id
    user_id = column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # human-readable UUID generated in chatRouter.py
    session_id = column(String(36), unique=True, nullable=False, index=True)

    title = column(String(255), nullable=True)

    status = column(ConversationStatus, nullable=False, default="active")
    message_count = column(Integer, nullable=False, default=0)
    completed_at = column(DateTime(timezone=True), nullable=True)

    # city this conversation is associated with (set from AG-UI state or user default)
    city_id = column(String(50), nullable=False, default="lucknow", index=True)

    # arbitrary extra data (e.g. language, topic, model name)
    extra_metadata = column(JSONB, nullable=True, default=dict)

    # one conversation → many messages
    messages = relationship(
        "ChatMessageModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessageModel.timestamp",
    )

    # one conversation → many AG-UI events (event-sourcing log)
    ag_ui_events = relationship(
        "AgUiEventModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AgUiEventModel.sequence",
    )

    # many conversations → one user
    user = relationship("UserModel", back_populates="conversations")

    def __repr__(self):
        return (
            f"<ConversationModel id={self.id} session_id={self.session_id!r}"
            f" user_id={self.user_id!r} status={self.status!r}>"
        )


# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------

class ChatMessageModel(Base):
    """A single message inside a conversation."""

    __tablename__ = "chat_messages"

    id = column(BigInteger, primary_key=True, autoincrement=True)

    # the UUID set in chatRouter.py
    message_id = column(String(36), unique=True, nullable=False, index=True)

    # FK → conversations.id
    conversation_id = column(
        BigInteger,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role = column(MessageRole, nullable=False)

    # use Text so very long LLM responses are not truncated
    content = column(Text, nullable=False)

    timestamp = column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # e.g. {"tokens": 123, "model": "gpt-4o"}
    extra_metadata = column(JSONB, nullable=True, default=dict)

    # many messages → one conversation
    conversation = relationship("ConversationModel", back_populates="messages")

    def __repr__(self):
        return (
            f"<ChatMessageModel id={self.id} message_id={self.message_id!r}"
            f" role={self.role!r} conversation_id={self.conversation_id!r}>"
        )


# ---------------------------------------------------------------------------
# AgUiEvent  ── append-only event-sourcing log for AG-UI streams
# ---------------------------------------------------------------------------

class AgUiEventModel(Base):
    """
    Stores every raw AG-UI event emitted during a conversation run.

    Columns
    -------
    conversation_id  FK → conversations.id
    sequence         0-based monotone counter within one conversation
    event            Full AG-UI event serialised as JSONB

    Design notes
    ------------
    * Append-only – events are never updated or deleted in normal flow.
    * (conversation_id, sequence) is UNIQUE so re-running a stopped stream
      cannot create duplicate rows.
    * Replaying these rows in sequence order recreates the exact UI state
      via CopilotKit's runtime.replayEvents().
    """

    __tablename__ = "ag_ui_events"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_ag_ui_events_conv_seq"),
    )

    id = column(BigInteger, primary_key=True, autoincrement=True)

    conversation_id = column(
        BigInteger,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Monotone counter scoped to the conversation
    sequence = column(Integer, nullable=False)

    # Full AG-UI event dict (e.g. {"type":"TEXT_MESSAGE_CONTENT","delta":"Hi"})
    event = column(JSONB, nullable=False)

    # many events → one conversation
    conversation = relationship("ConversationModel", back_populates="ag_ui_events")

    def __repr__(self):
        event_type = (self.event or {}).get("type", "?")
        return (
            f"<AgUiEventModel id={self.id} conversation_id={self.conversation_id}"
            f" seq={self.sequence} type={event_type!r}>"
        )

