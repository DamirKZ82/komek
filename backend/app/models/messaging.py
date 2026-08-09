"""Журнал SMS: без него невозможно разобрать жалобу «код не пришёл»."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, enum_column
from app.models.enums import SmsStatus


class SmsMessage(Entity):
    __tablename__ = "sms_messages"
    __table_args__ = (sa.Index("ix_sms_messages_phone_created", "phone", "created_at"),)

    phone: Mapped[str] = mapped_column(sa.String(20), index=True)
    # Текст храним усечённым: сам код входа в журнал не пишем.
    purpose: Mapped[str] = mapped_column(sa.String(32))  # otp | order_accepted | ...
    provider: Mapped[str] = mapped_column(sa.String(32))  # mobizon | log | ...
    status: Mapped[SmsStatus] = mapped_column(
        enum_column(SmsStatus, "sms_status"), default=SmsStatus.QUEUED, index=True
    )
    # Идентификатор сообщения у провайдера — по нему опрашиваем статус доставки.
    provider_message_id: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, index=True
    )
    segments: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    status_checked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
