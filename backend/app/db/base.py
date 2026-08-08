"""Базовый класс моделей, соглашения об именах и общие миксины."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Явные имена ограничений нужны, чтобы alembic мог их менять и откатывать.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_cls: type[Enum], name: str, **kwargs: Any) -> sa.Enum:
    """VARCHAR + CHECK вместо нативного PG-типа: добавлять значения проще и без блокировок."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=48,
        values_callable=lambda cls: [member.value for member in cls],
        **kwargs,
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )


class Entity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Обычная сущность: UUID-ключ + отметки времени."""

    __abstract__ = True
