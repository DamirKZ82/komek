"""Заказ и его жизненный цикл (п. 5.3 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, enum_column
from app.models.enums import (
    CancelledBy,
    OrderResponseStatus,
    OrderSource,
    OrderStatus,
    PriceUnit,
)


class Order(Entity):
    __tablename__ = "orders"
    __table_args__ = (
        sa.Index("ix_orders_customer_status", "customer_id", "status"),
        sa.Index("ix_orders_provider_status", "provider_user_id", "status"),
        sa.Index("ix_orders_open_feed", "status", "scheduled_start"),
    )

    # Человекочитаемый номер для поддержки и чеков: K-2026-000123.
    code: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    # Пусто, пока заявка не принята конкретным исполнителем.
    provider_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("services.id", ondelete="RESTRICT"), index=True
    )

    source: Mapped[OrderSource] = mapped_column(
        enum_column(OrderSource, "order_source"), default=OrderSource.CATALOG
    )
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus, "order_status"), default=OrderStatus.DRAFT, index=True
    )
    is_urgent: Mapped[bool] = mapped_column(sa.Boolean, default=False, index=True)

    # --- Время ---
    scheduled_start: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    scheduled_end: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    actual_end: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    # --- Место ---
    address_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )
    # Снимок адреса на момент заказа: правки в адресной книге не переписывают историю.
    address_snapshot: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    city_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("cities.id"), nullable=True)
    district_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("districts.id"), nullable=True, index=True
    )

    # --- Деньги ---
    price_unit: Mapped[PriceUnit] = mapped_column(enum_column(PriceUnit, "order_price_unit"))
    unit_price: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    estimated_units: Mapped[Decimal] = mapped_column(sa.Numeric(8, 2), default=Decimal("1"))
    estimated_total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    # Фактическая сумма считается по чек-ин/чек-ауту для почасовых заказов.
    final_units: Mapped[Decimal | None] = mapped_column(sa.Numeric(8, 2), nullable=True)
    final_total: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), nullable=True)
    commission_rate: Mapped[Decimal] = mapped_column(sa.Numeric(5, 4))
    commission_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), nullable=True)
    provider_payout_amount: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(12, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(sa.String(3), default="KZT")

    # --- Детали задачи ---
    comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Ответы на вопросы вертикали: возраст детей, диагноз, особые требования.
    details: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    required_qualification_ids: Mapped[list[str]] = mapped_column(sa.JSON, default=list)

    # --- Чек-ин / чек-аут по геолокации (по согласию) ---
    check_in_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    check_in_latitude: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    check_in_longitude: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    check_out_latitude: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    check_out_longitude: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    # --- Отмена ---
    cancelled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[CancelledBy | None] = mapped_column(
        enum_column(CancelledBy, "cancelled_by"), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    cancellation_penalty: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), nullable=True)

    recurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("order_recurrences.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    service: Mapped[Service] = relationship()  # noqa: F821
    responses: Mapped[list[OrderResponse]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    status_history: Mapped[list[OrderStatusHistory]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

    @property
    def is_open_for_responses(self) -> bool:
        return self.status == OrderStatus.PUBLISHED and self.provider_user_id is None


class OrderResponse(Entity):
    """Отклик исполнителя на опубликованную заявку (биржевой сценарий, п. 5.1 ТЗ)."""

    __tablename__ = "order_responses"
    __table_args__ = (
        sa.UniqueConstraint("order_id", "provider_user_id", name="uq_order_responses_provider"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[OrderResponseStatus] = mapped_column(
        enum_column(OrderResponseStatus, "order_response_status"),
        default=OrderResponseStatus.PENDING,
    )
    # Исполнитель может предложить свою цену, отличную от прайса заказчика.
    offered_price: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), nullable=True)
    message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    responded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    order: Mapped[Order] = relationship(back_populates="responses")


class OrderStatusHistory(Entity):
    """Полная история переходов — нужна для споров и аналитики воронки."""

    __tablename__ = "order_status_history"

    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[OrderStatus | None] = mapped_column(
        enum_column(OrderStatus, "history_from_status"), nullable=True
    )
    to_status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus, "history_to_status"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    order: Mapped[Order] = relationship(back_populates="status_history")


class OrderRecurrence(Entity):
    """Регулярное расписание: пн/ср/пт 18:00–21:00 с автосозданием заказов (этап 2)."""

    __tablename__ = "order_recurrences"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("services.id", ondelete="RESTRICT"))
    address_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )
    # Битовая маска дней недели: 0b0000001 = понедельник.
    weekday_mask: Mapped[int] = mapped_column(sa.SmallInteger)
    time_from: Mapped[time] = mapped_column(sa.Time)
    time_to: Mapped[time] = mapped_column(sa.Time)
    start_date: Mapped[date] = mapped_column(sa.Date)
    end_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    price_unit: Mapped[PriceUnit] = mapped_column(enum_column(PriceUnit, "recurrence_price_unit"))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    generated_until: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
