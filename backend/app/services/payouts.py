"""Реестр выплат исполнителям (п. 5.5 ТЗ).

Оплаченные заказы типов B/C группируются по исполнителям в реестры Payout.
Фактический перевод денег — TODO(acquiring): пока отметку «выплачено»
ставит финансовый администратор вручную.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError
from app.models.enums import OrderStatus, PayoutMethod, PayoutStatus
from app.models.order import Order
from app.models.payment import Payout, PayoutItem
from app.models.user import User
from app.services.notifications import notify_user


async def build_payout_registry(session: AsyncSession) -> list[Payout]:
    """Создаёт реестры по всем оплаченным заказам, ещё не попавшим в выплаты."""
    already_paid_orders = sa.select(PayoutItem.order_id)
    orders = (
        await session.scalars(
            sa.select(Order).where(
                Order.status == OrderStatus.PAID,
                Order.provider_user_id.is_not(None),
                Order.provider_payout_amount.is_not(None),
                Order.provider_payout_amount > 0,
                Order.id.not_in(already_paid_orders),
            )
        )
    ).all()

    by_provider: dict[uuid.UUID, list[Order]] = {}
    for order in orders:
        by_provider.setdefault(order.provider_user_id, []).append(order)

    batch_id = f"B-{datetime.now(UTC):%Y%m%d}-{secrets.randbelow(10**4):04d}"
    payouts: list[Payout] = []
    for provider_id, provider_orders in by_provider.items():
        total = sum(
            (o.provider_payout_amount for o in provider_orders), start=Decimal("0")
        )
        payout = Payout(
            provider_user_id=provider_id,
            method=PayoutMethod.KASPI,  # реквизиты исполнителя — этап эквайринга
            amount=total,
            batch_id=batch_id,
            period_start=min(o.scheduled_start for o in provider_orders).date(),
            period_end=max(o.scheduled_start for o in provider_orders).date(),
        )
        session.add(payout)
        await session.flush()
        for order in provider_orders:
            session.add(
                PayoutItem(
                    payout_id=payout.id,
                    order_id=order.id,
                    amount=order.provider_payout_amount,
                    commission_amount=order.commission_amount or Decimal("0"),
                )
            )
        payouts.append(payout)

    if not payouts:
        return []
    await session.flush()
    # Перечитываем с загруженными позициями: сериализация не должна лениво грузить.
    rows = await session.scalars(
        sa.select(Payout)
        .where(Payout.id.in_([p.id for p in payouts]))
        .options(selectinload(Payout.items))
    )
    return list(rows)


async def list_payouts(
    session: AsyncSession, status: PayoutStatus | None, limit: int, offset: int
) -> tuple[list[Payout], int]:
    stmt = sa.select(Payout).options(selectinload(Payout.items))
    if status is not None:
        stmt = stmt.where(Payout.status == status)
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = (
        await session.scalars(
            stmt.order_by(Payout.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def mark_payout_paid(
    session: AsyncSession, admin: User, payout_id: uuid.UUID
) -> Payout:
    payout = await session.scalar(
        sa.select(Payout)
        .where(Payout.id == payout_id)
        .options(selectinload(Payout.items))
        .with_for_update()
    )
    if payout is None:
        raise NotFoundError("Реестр не найден")
    if payout.status == PayoutStatus.PAID:
        raise ConflictError("Уже выплачено", code="already_paid")
    # TODO(acquiring): фактический перевод на карту/Kaspi исполнителя.
    payout.status = PayoutStatus.PAID
    payout.executed_at = datetime.now(UTC)
    await notify_user(
        session,
        payout.provider_user_id,
        "Выплата отправлена",
        f"Вам выплачено {payout.amount} ₸ по реестру {payout.batch_id}",
    )
    return payout
