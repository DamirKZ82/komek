"""Платежи, выплаты и тарифы комиссии (п. 5.5 ТЗ).

Модель денег: холд при подтверждении заказа → списание после чек-аута →
выплата исполнителю за вычетом комиссии. Реквизиты карт не хранятся —
только маскированный хвост и токен эквайера.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, enum_column
from app.models.enums import (
    PaymentProvider,
    PaymentStatus,
    PayoutMethod,
    PayoutStatus,
)


class Payment(Entity):
    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    payer_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="RESTRICT"))
    provider: Mapped[PaymentProvider] = mapped_column(
        enum_column(PaymentProvider, "payment_provider")
    )
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus, "payment_status"), default=PaymentStatus.PENDING, index=True
    )
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    captured_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), nullable=True)
    refunded_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(sa.String(3), default="KZT")

    # Идентификатор транзакции на стороне эквайера/Kaspi — ключ сверки.
    psp_reference: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    card_mask: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    # Ключ идемпотентности: повторный «оплатить» не создаёт второй холд.
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(64), unique=True, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    held_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    # Фискальный чек ОФД — юридическая обвязка платёжного агента (п. 5.5 ТЗ).
    receipt_number: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)


class Payout(Entity):
    """Реестр выплат исполнителю: пачка заказов за период."""

    __tablename__ = "payouts"

    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[PayoutStatus] = mapped_column(
        enum_column(PayoutStatus, "payout_status"), default=PayoutStatus.SCHEDULED, index=True
    )
    method: Mapped[PayoutMethod] = mapped_column(enum_column(PayoutMethod, "payout_method"))
    destination_mask: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    currency: Mapped[str] = mapped_column(sa.String(3), default="KZT")
    period_start: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    psp_reference: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    items: Mapped[list[PayoutItem]] = relationship(
        back_populates="payout", cascade="all, delete-orphan"
    )


class PayoutItem(Entity):
    __tablename__ = "payout_items"
    __table_args__ = (sa.UniqueConstraint("order_id", name="uq_payout_items_order"),)

    payout_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("payouts.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("orders.id", ondelete="RESTRICT"))
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    commission_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))

    payout: Mapped[Payout] = relationship(back_populates="items")


class CommissionRule(Entity):
    """Ставка комиссии: глобальная или для конкретной категории, с датой начала действия."""

    __tablename__ = "commission_rules"

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("service_categories.id", ondelete="CASCADE"), nullable=True
    )
    rate: Mapped[Decimal] = mapped_column(sa.Numeric(5, 4))
    valid_from: Mapped[date] = mapped_column(sa.Date)
    valid_until: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    comment: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)


class PromoCode(Entity):
    __tablename__ = "promo_codes"

    code: Mapped[str] = mapped_column(sa.String(32), unique=True, index=True)
    discount_percent: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(sa.Integer, default=1)
    valid_from: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
