"""Column types shared by the models.

`enum_column` stores an enum as a plain VARCHAR holding the enum *value* ("in_progress"), exactly like the original
`String(30)` columns, so no data migration is needed, while Python code still receives real enum members.
"""
from sqlalchemy import Enum


def enum_column(enum_cls, length: int = 30) -> Enum:
    return Enum(
        enum_cls, native_enum=False, length=length, create_constraint=False, validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
    )
