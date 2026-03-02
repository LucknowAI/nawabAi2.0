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

    # arbitrary extra data (e.g. language, topic, model name)
    extra_metadata = column(JSONB, nullable=True, default=dict)

    # one conversation → many messages
    messages = relationship(
        "ChatMessageModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessageModel.timestamp",
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

