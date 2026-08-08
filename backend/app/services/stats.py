"""Аналитика-минимум для админки (п. 5.7 ТЗ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus, ReviewStatus
from app.models.order import Order
from app.models.provider import ProviderProfile
from app.models.review import Review
from app.models.user import User


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
