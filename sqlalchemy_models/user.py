"""
SQLAlchemy ORM model for users.

Table
-----
users  – one row per unique user; populated from Google OAuth data.
"""

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import relationship

from sqlalchemy_models.base import Base
from src.utils.utils_alembic import column


class UserModel(Base):
    """
    Represents a registered user.

    All user-identifying columns are sourced from Google's ID-token payload
    at first login and updated on subsequent logins.
    """

    __tablename__ = "users"

    # -----------------------------------------------------------------------
    # Primary key
    # -----------------------------------------------------------------------
    id = column(BigInteger, primary_key=True, autoincrement=True)

    # -----------------------------------------------------------------------
    # Google-sourced identity fields
    # -----------------------------------------------------------------------

    # `sub` claim from Google ID token – globally unique per Google account
    google_id    = column(String(128), unique=True, nullable=False, index=True)

    email        = column(String(255),  unique=True, nullable=False, index=True)
    full_name    = column(String(255),  nullable=True)
    given_name   = column(String(128),  nullable=True)
    family_name  = column(String(128),  nullable=True)

    # Profile picture URL returned by Google
    picture      = column(String(1024), nullable=True)

    # Whether Google has verified the email address (`email_verified` claim)
    email_verified = column(Boolean, nullable=False, default=False)

    # -----------------------------------------------------------------------
    # Auth / meta
    # -----------------------------------------------------------------------
    # Always "google" for now; kept for future extensibility
    auth_provider = column(String(32),  nullable=False, default="google")

    last_login   = column(DateTime(timezone=True), nullable=True)

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    conversations = relationship(
        "ConversationModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<UserModel id={self.id} email={self.email!r}>"
