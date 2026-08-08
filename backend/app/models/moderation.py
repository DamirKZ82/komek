"""Жалобы, споры и аудит действий персонала (п. 4.4 и 5.7 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, enum_column
from app.models.enums import ComplaintCategory, ComplaintStatus


class Complaint(Entity):
    """Жалоба категории safety автоматически приостанавливает профиль до разбора."""

    __tablename__ = "complaints"

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[ComplaintCategory] = mapped_column(
        enum_column(ComplaintCategory, "complaint_category"), index=True
    )
    status: Mapped[ComplaintStatus] = mapped_column(
        enum_column(ComplaintStatus, "complaint_status"), default=ComplaintStatus.OPEN, index=True
    )
    description: Mapped[str] = mapped_column(sa.Text)
    attachments: Mapped[list[str]] = mapped_column(sa.JSON, default=list)

    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    compensation_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    # Профиль приостановлен автоматически — при закрытии жалобы нужно снять блокировку.
    auto_suspended: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class AuditLog(Entity):
    """Кто из персонала что сделал: требование к админке (п. 6 ТЗ)."""

    __tablename__ = "audit_logs"
    __table_args__ = (sa.Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(sa.String(64), index=True)
    entity_type: Mapped[str] = mapped_column(sa.String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
