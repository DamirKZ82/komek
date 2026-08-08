"""Встроенный чат с антидизинтермедиацией (п. 5.4 ТЗ).

До оплаты телефоны и мессенджеры маскируются: в `body` лежит уже отфильтрованный текст,
исходник — в `raw_body` и доступен только модератору при разборе жалобы.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, enum_column
from app.models.enums import MessageType


class ChatThread(Entity):
    __tablename__ = "chat_threads"
    __table_args__ = (
        sa.UniqueConstraint("customer_id", "provider_user_id", name="uq_chat_threads_pair"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Последний заказ, из которого пришли в диалог — для контекста в шапке чата.
    last_order_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    # Контакты раскрываются после оплаты заказа между этой парой.
    contacts_unlocked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, index=True
    )
    is_blocked: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )


class ChatMessage(Entity):
    __tablename__ = "chat_messages"
    __table_args__ = (sa.Index("ix_chat_messages_thread_created", "thread_id", "created_at"),)

    thread_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("chat_threads.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    message_type: Mapped[MessageType] = mapped_column(
        enum_column(MessageType, "message_type"), default=MessageType.TEXT
    )
    body: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    raw_body: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    contacts_masked: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    attachment_key: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)  # голосовые
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    thread: Mapped[ChatThread] = relationship(back_populates="messages")
