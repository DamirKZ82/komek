"""Монетизация (п. 5.8 ТЗ): комиссия типов B/C и fee за подбор типа A.

Реальный эквайринг (Kaspi Pay / карты) не подключён: холд и списание имитируются
записями Payment со статусами. Точки интеграции помечены TODO(acquiring) —
при подключении шлюза меняется только этот модуль.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.catalog import Service
from app.models.enums import (
    MonetizationType,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
    PlacementFeeStatus,
    PriceUnit,
)
from app.models.order import Order
from app.models.payment import Payment
from app.models.placement import Placement
from app.models.user import User
from app.services.notifications import notify_user

# Пересчёт тарифа исполнителя в месячную ставку для расчёта fee (ориентир):
# смена ≈ 22 рабочих дня, час ≈ 8 часов × 22 дня.
_MONTHLY_MULTIPLIERS: dict[PriceUnit, Decimal] = {
    PriceUnit.MONTH: Decimal("1"),
    PriceUnit.DAY: Decimal("22"),
    PriceUnit.SHIFT: Decimal("22"),
    PriceUnit.HOUR: Decimal("176"),
}


def estimate_monthly_rate(unit_price: Decimal, unit: PriceUnit) -> Decimal:
    return (unit_price * _MONTHLY_MULTIPLIERS[unit]).quantize(Decimal("0.01"))


async def setup_order_billing(session: AsyncSession, order: Order) -> None:
    """Вызывается при подтверждении заказа: холд (B/C) или создание fee за подбор (A)."""
    service = await session.get(Service, order.service_id)
    assert service is not None

    if service.monetization_type == MonetizationType.PLACEMENT_FEE:
        # Тип A: пара выводится из комиссионной логики, платформа берёт разовый fee.
        order.commission_rate = Decimal("0")
        monthly = estimate_monthly_rate(order.unit_price, order.price_unit)
        fee = (monthly * settings.placement_fee_rate).quantize(Decimal("0.01"))

        # Гарантия замены: если у заказчика есть активная гарантия с запрошенной
        # заменой — повторный подбор бесплатен.
        prior = await session.scalar(
            sa.select(Placement)
            .where(
                Placement.customer_id == order.customer_id,
                Placement.replacement_requested_at.is_not(None),
                Placement.guarantee_until >= datetime.now(UTC),
            )
            .order_by(Placement.created_at.desc())
            .limit(1)
        )
        placement = Placement(
            order_id=order.id,
            customer_id=order.customer_id,
            provider_user_id=order.provider_user_id,
            monthly_rate=monthly,
            fee_amount=Decimal("0") if prior is not None else fee,
            fee_status=(
                PlacementFeeStatus.WAIVED if prior is not None else PlacementFeeStatus.PENDING
            ),
            replacement_of_id=prior.id if prior is not None else None,
        )
        if prior is not None:
            placement.guarantee_until = prior.guarantee_until  # гарантия не продлевается
        session.add(placement)
    else:
        # Типы B/C: оплата только через платформу.
        # TODO(acquiring): здесь создаётся холд через Kaspi Pay / эквайринг.
        session.add(
            Payment(
                order_id=order.id,
                payer_id=order.customer_id,
                provider=PaymentProvider.CARD,
                status=PaymentStatus.HELD,
                amount=order.estimated_total,
                held_at=datetime.now(UTC),
                idempotency_key=f"hold-{order.id}",
            )
        )


async def pay_order(session: AsyncSession, customer: User, order_id: uuid.UUID) -> Order:
    """Списание после чек-аута (типы B/C). Пока шлюза нет — имитация capture."""
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Заказ не найден")
    if order.status != OrderStatus.COMPLETED:
        raise ConflictError("Оплата доступна после завершения заказа", code="order_not_completed")

    payment = await session.scalar(
        sa.select(Payment).where(
            Payment.order_id == order_id, Payment.status == PaymentStatus.HELD
        )
    )
    now = datetime.now(UTC)
    # TODO(acquiring): capture холда на сумму final_total, разницу — вернуть.
    if payment is not None:
        payment.status = PaymentStatus.CAPTURED
        payment.captured_amount = order.final_total
        payment.captured_at = now
    else:
        session.add(
            Payment(
                order_id=order.id,
                payer_id=customer.id,
                provider=PaymentProvider.CARD,
                status=PaymentStatus.CAPTURED,
                amount=order.final_total or order.estimated_total,
                captured_amount=order.final_total,
                captured_at=now,
                idempotency_key=f"capture-{order.id}",
            )
        )

    order.paid_at = now
    # Переход COMPLETED → PAID делает вызывающий модуль orders (стейт-машина там).
    if order.provider_user_id is not None:
        await notify_user(
            session,
            order.provider_user_id,
            "Заказ оплачен",
            f"Заказ {order.code} оплачен, выплата будет в ближайшем реестре",
            {"order_id": str(order.id)},
        )
    return order


# --- Fee за подбор (тип A) ----------------------------------------------------


async def get_my_placements(session: AsyncSession, customer: User) -> list[Placement]:
    rows = await session.scalars(
        sa.select(Placement)
        .where(Placement.customer_id == customer.id)
        .order_by(Placement.created_at.desc())
    )
    return list(rows)


async def pay_placement_fee(
    session: AsyncSession, customer: User, placement_id: uuid.UUID
) -> Placement:
    placement = await session.get(Placement, placement_id, with_for_update=True)
    if placement is None or placement.customer_id != customer.id:
        raise NotFoundError("Подбор не найден")
    if placement.fee_status != PlacementFeeStatus.PENDING:
        raise ConflictError("Fee уже оплачен или не требуется", code="fee_not_pending")

    now = datetime.now(UTC)
    # TODO(acquiring): списание fee через платёжный шлюз.
    session.add(
        Payment(
            order_id=placement.order_id,
            payer_id=customer.id,
            provider=PaymentProvider.CARD,
            status=PaymentStatus.CAPTURED,
            amount=placement.fee_amount,
            captured_amount=placement.fee_amount,
            captured_at=now,
            idempotency_key=f"placement-fee-{placement.id}",
        )
    )
    placement.fee_status = PlacementFeeStatus.PAID
    placement.fee_paid_at = now
    placement.guarantee_until = now + timedelta(days=settings.placement_guarantee_days)

    await notify_user(
        session,
        placement.provider_user_id,
        "Подбор подтверждён",
        "Заказчик оплатил подбор — договоритесь о выходе на работу",
    )
    return placement


async def request_replacement(
    session: AsyncSession, customer: User, placement_id: uuid.UUID, reason: str
) -> Placement:
    """Гарантия замены: в течение 30 дней повторный подбор бесплатен (п. 5.8 ТЗ)."""
    placement = await session.get(Placement, placement_id, with_for_update=True)
    if placement is None or placement.customer_id != customer.id:
        raise NotFoundError("Подбор не найден")
    if placement.fee_status != PlacementFeeStatus.PAID:
        raise ForbiddenError("Гарантия действует после оплаты fee", code="fee_not_paid")
    if not placement.guarantee_active:
        raise ConflictError("Срок гарантии замены истёк", code="guarantee_expired")
    if placement.replacement_requested_at is not None:
        raise ConflictError("Замена уже запрошена", code="already_requested")

    placement.replacement_requested_at = datetime.now(UTC)
    placement.replacement_reason = reason
    return placement
