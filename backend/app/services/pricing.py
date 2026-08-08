"""Действующая ставка комиссии (п. 5.7 ТЗ: управление тарифами из админки).

Приоритет: правило для категории услуги → глобальное правило → значение из настроек.
Среди подходящих берётся правило с самой поздней датой начала действия.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.catalog import Service
from app.models.payment import CommissionRule


async def resolve_commission_rate(
    session: AsyncSession, service_id: uuid.UUID, on_date: date | None = None
) -> Decimal:
    today = on_date or date.today()
    service = await session.get(Service, service_id)
    category_id = service.category_id if service is not None else None

    stmt = (
        sa.select(CommissionRule)
        .where(
            CommissionRule.valid_from <= today,
            sa.or_(
                CommissionRule.valid_until.is_(None),
                CommissionRule.valid_until >= today,
            ),
            sa.or_(
                CommissionRule.category_id == category_id,
                CommissionRule.category_id.is_(None),
            ),
        )
        # Правило категории важнее глобального; при равенстве — более свежее.
        .order_by(
            CommissionRule.category_id.is_(None).asc(),
            CommissionRule.valid_from.desc(),
        )
        .limit(1)
    )
    rule = await session.scalar(stmt)
    return rule.rate if rule is not None else settings.default_commission_rate
