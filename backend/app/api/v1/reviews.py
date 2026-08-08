from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter

from app.api.deps import CurrentUser, PaginationDep, SessionDep
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.enums import ReviewDirection, ReviewStatus
from app.models.review import Review
from app.schemas.common import Page
from app.schemas.review import ReviewCreateIn, ReviewOut, ReviewReplyIn
from app.services import reviews as review_service

router = APIRouter(tags=["reviews"])


@router.post("/orders/{order_id}/reviews", response_model=ReviewOut, status_code=201)
async def create_review(
    order_id: uuid.UUID, data: ReviewCreateIn, user: CurrentUser, session: SessionDep
) -> ReviewOut:
    review = await review_service.create_review(session, user.id, order_id, data)
    return ReviewOut.model_validate(review)


@router.get("/providers/{user_id}/reviews", response_model=Page[ReviewOut])
async def provider_reviews(
    user_id: uuid.UUID, session: SessionDep, pagination: PaginationDep
) -> Page[ReviewOut]:
    stmt = sa.select(Review).where(
        Review.target_id == user_id,
        Review.direction == ReviewDirection.CUSTOMER_TO_PROVIDER,
        Review.status == ReviewStatus.PUBLISHED,
    )
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = (
        await session.scalars(
            stmt.order_by(Review.published_at.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
    ).all()
    return Page(
        items=[ReviewOut.model_validate(r) for r in rows],
        total=int(total or 0),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("/reviews/{review_id}/reply", response_model=ReviewOut)
async def reply_to_review(
    review_id: uuid.UUID, data: ReviewReplyIn, user: CurrentUser, session: SessionDep
) -> ReviewOut:
    review = await session.get(Review, review_id)
    if review is None:
        raise NotFoundError("Отзыв не найден")
    if review.target_id != user.id:
        raise ForbiddenError("Отвечать может только адресат отзыва")
    if review.reply_text is not None:
        raise ConflictError("Ответ уже оставлен")
    review.reply_text = data.text
    review.reply_at = datetime.now(UTC)
    return ReviewOut.model_validate(review)
