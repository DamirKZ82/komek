"""Отзывы: только по оплаченным заказам, окно 14 дней, модерация низких оценок (п. 5.6 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.datetime_utils import ensure_utc
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.enums import OrderStatus, ReviewDirection, ReviewStatus
from app.models.order import Order
from app.models.provider import ProviderProfile
from app.models.review import Review
from app.schemas.review import ReviewCreateIn


async def create_review(
    session: AsyncSession, author_id: uuid.UUID, order_id: uuid.UUID, data: ReviewCreateIn
) -> Review:
    order = await session.get(Order, order_id)
    if order is None:
        raise NotFoundError("Заказ не найден")
    if order.status != OrderStatus.PAID:
        raise ConflictError(
            "Отзыв можно оставить только по оплаченному заказу", code="order_not_paid"
        )

    if author_id == order.customer_id:
        direction = ReviewDirection.CUSTOMER_TO_PROVIDER
        target_id = order.provider_user_id
    elif author_id == order.provider_user_id:
        direction = ReviewDirection.PROVIDER_TO_CUSTOMER
        target_id = order.customer_id
    else:
        raise ForbiddenError()
    if target_id is None:
        raise ConflictError("У заказа нет второй стороны")

    now = datetime.now(UTC)
    deadline = ensure_utc(
        order.paid_at or order.completed_at or order.updated_at
    ) + timedelta(days=settings.review_window_days)
    if now > deadline:
        raise ConflictError("Срок для отзыва истёк", code="review_window_closed")

    existing = await session.scalar(
        sa.select(Review).where(Review.order_id == order_id, Review.direction == direction)
    )
    if existing is not None:
        raise ConflictError("Отзыв уже оставлен", code="already_reviewed")

    # Оценки 1–2 уходят в ручную модерацию, остальные публикуются сразу.
    needs_moderation = data.rating <= 2
    review = Review(
        order_id=order_id,
        author_id=author_id,
        target_id=target_id,
        direction=direction,
        rating=data.rating,
        rating_punctuality=data.rating_punctuality,
        rating_attitude=data.rating_attitude,
        rating_communication=data.rating_communication,
        text=data.text,
        status=ReviewStatus.PENDING if needs_moderation else ReviewStatus.PUBLISHED,
        published_at=None if needs_moderation else now,
        editable_until=now + timedelta(hours=settings.review_edit_window_hours),
    )
    session.add(review)
    await session.flush()

    is_for_provider = direction == ReviewDirection.CUSTOMER_TO_PROVIDER
    if review.status == ReviewStatus.PUBLISHED and is_for_provider:
        await recalc_provider_rating(session, target_id)
    return review


async def recalc_provider_rating(session: AsyncSession, provider_user_id: uuid.UUID) -> None:
    row = (
        await session.execute(
            sa.select(sa.func.avg(Review.rating), sa.func.count()).where(
                Review.target_id == provider_user_id,
                Review.direction == ReviewDirection.CUSTOMER_TO_PROVIDER,
                Review.status == ReviewStatus.PUBLISHED,
            )
        )
    ).one()
    avg, count = row
    profile = await session.get(ProviderProfile, provider_user_id)
    if profile is not None:
        profile.rating_avg = (
            Decimal(str(round(float(avg), 2))) if avg is not None else None
        )
        profile.rating_count = int(count)
