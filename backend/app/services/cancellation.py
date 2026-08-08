"""Расчёт штрафа за отмену (п. 5.3 ТЗ)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetime_utils import ensure_utc
from app.models.cancellation import CancellationRule
from app.models.enums import OrderStatus
from app.models.order import Order

# Штраф применяется только когда исполнитель уже закрепился за заказом.
_PENALTY_STATUSES = {OrderStatus.ACCEPTED, OrderStatus.CONFIRMED}


async def calculate_penalty(session: AsyncSession, order: Order) -> Decimal:
    """Штраф заказчику за отмену: % от расчётной суммы по действующим правилам."""
    if order.status not in _PENALTY_STATUSES:
        return Decimal("0")

    hours_left = (
        ensure_utc(order.scheduled_start) - datetime.now(UTC)
    ).total_seconds() / 3600
    if hours_left < 0:
        hours_left = 0

    rules = (
        await session.scalars(
            sa.select(CancellationRule)
            .where(CancellationRule.is_active.is_(True))
            .order_by(CancellationRule.hours_before.asc())
        )
    ).all()

    # Правила отсортированы по возрастанию порога: берём первое, куда попадаем.
    for rule in rules:
        if hours_left < rule.hours_before:
            return (
                order.estimated_total * rule.penalty_percent / Decimal("100")
            ).quantize(Decimal("0.01"))
    return Decimal("0")
