"""Аналитика-минимум для админки (п. 5.7 ТЗ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus, PaymentStatus, ReviewStatus
from app.models.order import Order
from app.models.provider import ProviderProfile
from app.models.review import Review
from app.models.user import User


async def collect_reconciliation(session: AsyncSession) -> dict[str, Any]:
    """Сверка заказов с платежами (п. 5.7 ТЗ «сверка с эквайрингом»).

    Показывает расхождения, которые требуют ручного разбора: оплаченные заказы
    без списания, зависшие холды по закрытым заказам, неудавшиеся платежи.
    """
    from app.models.payment import Payment  # noqa: PLC0415 — только для сверки

    # Оплаченные заказы, по которым нет успешного списания.
    captured_orders = sa.select(Payment.order_id).where(
        Payment.status.in_([PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED])
    )
    paid_without_capture = (
        await session.scalars(
            sa.select(Order.code).where(
                Order.status == OrderStatus.PAID, Order.id.not_in(captured_orders)
            )
        )
    ).all()

    # Холды по заказам, которые уже закрыты — деньги висят у заказчика.
    stale_holds = (
        await session.execute(
            sa.select(Order.code, Payment.amount)
            .join(Order, Order.id == Payment.order_id)
            .where(
                Payment.status == PaymentStatus.HELD,
                Order.status.in_([OrderStatus.CANCELLED, OrderStatus.EXPIRED]),
            )
        )
    ).all()

    failed = (
        await session.execute(
            sa.select(Order.code, Payment.error_message)
            .join(Order, Order.id == Payment.order_id)
            .where(Payment.status == PaymentStatus.FAILED)
            .limit(50)
        )
    ).all()

    return {
        "paid_without_capture": list(paid_without_capture),
        "stale_holds": [{"order": code, "amount": str(amount)} for code, amount in stale_holds],
        "failed_payments": [
            {"order": code, "error": error} for code, error in failed
        ],
    }


async def collect_stats(session: AsyncSession) -> dict[str, Any]:
    month_ago = datetime.now(UTC) - timedelta(days=30)

    orders_by_status = {
        status.value: count
        for status, count in (
            await session.execute(
                sa.select(Order.status, sa.func.count()).group_by(Order.status)
            )
        ).all()
    }

    gmv, commission = (
        await session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(Order.final_total), 0),
                sa.func.coalesce(sa.func.sum(Order.commission_amount), 0),
            ).where(Order.status == OrderStatus.PAID)
        )
    ).one()

    providers_by_level = {
        level.value: count
        for level, count in (
            await session.execute(
                sa.select(ProviderProfile.verification_level, sa.func.count()).group_by(
                    ProviderProfile.verification_level
                )
            )
        ).all()
    }

    users_total = await session.scalar(sa.select(sa.func.count()).select_from(User))
    orders_30d = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Order)
        .where(Order.created_at >= month_ago)
    )
    urgent_30d = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Order)
        .where(Order.created_at >= month_ago, Order.is_urgent.is_(True))
    )
    pending_reviews = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Review)
        .where(Review.status == ReviewStatus.PENDING)
    )

    return {
        "orders_by_status": orders_by_status,
        "gmv_paid": str(Decimal(str(gmv))),
        "commission_earned": str(Decimal(str(commission))),
        "providers_by_level": providers_by_level,
        "users_total": int(users_total or 0),
        "orders_last_30d": int(orders_30d or 0),
        "urgent_orders_last_30d": int(urgent_30d or 0),
        "reviews_pending_moderation": int(pending_reviews or 0),
    }
