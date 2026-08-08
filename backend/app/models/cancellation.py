"""Правила отмены заказов (п. 5.3 ТЗ): штраф зависит от времени до начала."""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity


class CancellationRule(Entity):
    """«Если до начала осталось меньше hours_before часов — штраф penalty_percent%».

    Правила настраиваются админом; применяется правило с наименьшим подходящим
    порогом. Отмена раньше самого большого порога — бесплатна.
    """

    __tablename__ = "cancellation_rules"
    __table_args__ = (
        sa.CheckConstraint("hours_before >= 0", name="hours_non_negative"),
        sa.CheckConstraint(
            "penalty_percent >= 0 AND penalty_percent <= 100", name="penalty_range"
        ),
        sa.UniqueConstraint("hours_before", name="uq_cancellation_rules_hours"),
    )

    hours_before: Mapped[int] = mapped_column(sa.Integer)
    penalty_percent: Mapped[Decimal] = mapped_column(sa.Numeric(5, 2))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
