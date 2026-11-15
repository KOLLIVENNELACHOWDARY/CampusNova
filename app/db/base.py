from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The one declarative base for every model (Alembic autogenerate reads Base.metadata).

    Both the classic `Column(...)` style used by the original team models and the typed `Mapped[...]` style work on it.
    """
