from sqlalchemy.orm import Mapped, mapped_column
from typing import TypeVar

T = TypeVar("T")

def column(*args, **kwargs) -> Mapped[T]:
    return mapped_column(*args, **kwargs)