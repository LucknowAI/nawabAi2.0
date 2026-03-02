from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy models.

    Every concrete model automatically inherits `created_at` and `updated_at`
    columns without having to declare them manually.
    """

    @declared_attr
    def created_at(cls):
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )

    @declared_attr
    def updated_at(cls):
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )
