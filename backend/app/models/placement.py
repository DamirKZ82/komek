"""Подбор постоянного исполнителя — монетизация типа A (п. 5.8 ТЗ).

Заказчик платит разовый fee в момент подтверждения найма; в fee включена
гарантия замены 30 дней. После подбора пара выводится из комиссионной логики.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, enum_column
from app.models.enums import PlacementFeeStatus


class Placement(Entity):
    __tablename__ = "placements"

    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("orders.id", ondelete="RESTRICT"), unique=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )

    # Месячная ставка исполнителя, от которой посчитан fee (снимок на момент найма).
    monthly_rate: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    fee_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    fee_status: Mapped[PlacementFeeStatus] = mapped_column(
        enum_column(PlacementFeeStatus, "placement_fee_status"),
        default=PlacementFeeStatus.PENDING,
        index=True,
    )
    fee_paid_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    # Гарантия замены: до этой даты повторный подбор бесплатен.
    guarantee_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    replacement_requested_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    replacement_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Если этот подбор — бесплатная замена по гарантии, ссылка на исходный.
    replacement_of_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("placements.id", ondelete="SET NULL"), nullable=True
    )

    @property
    def guarantee_active(self) -> bool:
        if self.guarantee_until is None:
            return False
        until = self.guarantee_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        return datetime.now(UTC) <= until
