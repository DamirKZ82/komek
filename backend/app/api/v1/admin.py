"""Эндпоинты модерации и финансов (доступ — только staff)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentStaff, PaginationDep, SessionDep
from app.core.errors import ConflictError, NotFoundError
from app.models.cancellation import CancellationRule
from app.models.enums import (
    ComplaintStatus,
    PayoutMethod,
    PayoutStatus,
    ReviewDirection,
    ReviewStatus,
    VerificationRequestStatus,
)
from app.models.moderation import AuditLog, Complaint
from app.models.payment import CommissionRule, PromoCode
from app.models.review import Review
from app.models.verification import VerificationRequest
from app.schemas.common import ApiModel, Ok, Page
from app.schemas.moderation import (
    ComplaintOut,
    ComplaintResolveIn,
    VerificationDecisionIn,
    VerificationRequestOut,
)
from app.schemas.review import ReviewOut
from app.services import moderation as moderation_service
from app.services import payouts as payout_service
from app.services.reviews import recalc_provider_rating
from app.services.stats import collect_reconciliation, collect_stats

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/verification-requests", response_model=Page[VerificationRequestOut])
async def verification_queue(
    staff: CurrentStaff,
    session: SessionDep,
    pagination: PaginationDep,
    status: VerificationRequestStatus | None = VerificationRequestStatus.SUBMITTED,
) -> Page[VerificationRequestOut]:
    stmt = sa.select(VerificationRequest)
    if status is not None:
        stmt = stmt.where(VerificationRequest.status == status)
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = await session.scalars(
        stmt.order_by(VerificationRequest.submitted_at.asc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page(
        items=[VerificationRequestOut.model_validate(r) for r in rows],
        total=int(total or 0),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("/verification-requests/{request_id}/decision", response_model=VerificationRequestOut)
async def decide_verification(
    request_id: uuid.UUID,
    data: VerificationDecisionIn,
    staff: CurrentStaff,
    session: SessionDep,
) -> VerificationRequestOut:
    request = await moderation_service.decide_verification(session, staff, request_id, data)
    return VerificationRequestOut.model_validate(request)


@router.get("/complaints", response_model=Page[ComplaintOut])
async def complaints_queue(
    staff: CurrentStaff,
    session: SessionDep,
    pagination: PaginationDep,
    status: ComplaintStatus | None = ComplaintStatus.OPEN,
) -> Page[ComplaintOut]:
    stmt = sa.select(Complaint)
    if status is not None:
        stmt = stmt.where(Complaint.status == status)
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = await session.scalars(
        stmt.order_by(Complaint.created_at.asc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page(
        items=[ComplaintOut.model_validate(c) for c in rows],
        total=int(total or 0),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("/complaints/{complaint_id}/resolve", response_model=ComplaintOut)
async def resolve_complaint(
    complaint_id: uuid.UUID,
    data: ComplaintResolveIn,
    staff: CurrentStaff,
    session: SessionDep,
) -> ComplaintOut:
    complaint = await moderation_service.resolve_complaint(session, staff, complaint_id, data)
    return ComplaintOut.model_validate(complaint)


class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/users/{user_id}/suspend", response_model=Ok)
async def suspend_user(
    user_id: uuid.UUID, data: SuspendIn, staff: CurrentStaff, session: SessionDep
) -> Ok:
    await moderation_service.suspend_user(session, staff, user_id, data.reason)
    return Ok()


# --- Модерация отзывов (п. 5.6 ТЗ) --------------------------------------------


class ReviewDecisionIn(BaseModel):
    publish: bool
    notes: str | None = Field(default=None, max_length=1000)


@router.get("/reviews", response_model=Page[ReviewOut])
async def reviews_queue(
    staff: CurrentStaff, session: SessionDep, pagination: PaginationDep
) -> Page[ReviewOut]:
    stmt = sa.select(Review).where(Review.status == ReviewStatus.PENDING)
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = (
        await session.scalars(
            stmt.order_by(Review.created_at.asc())
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


@router.post("/reviews/{review_id}/decision", response_model=ReviewOut)
async def decide_review(
    review_id: uuid.UUID, data: ReviewDecisionIn, staff: CurrentStaff, session: SessionDep
) -> ReviewOut:
    review = await session.get(Review, review_id, with_for_update=True)
    if review is None:
        raise NotFoundError("Отзыв не найден")
    if review.status != ReviewStatus.PENDING:
        raise ConflictError("Отзыв уже рассмотрен", code="already_decided")

    review.moderation_notes = data.notes
    if data.publish:
        review.status = ReviewStatus.PUBLISHED
        review.published_at = datetime.now(UTC)
        if review.direction == ReviewDirection.CUSTOMER_TO_PROVIDER:
            await recalc_provider_rating(session, review.target_id)
    else:
        review.status = ReviewStatus.REJECTED
    return ReviewOut.model_validate(review)


# --- Финансы: реестры выплат (п. 5.5 ТЗ) --------------------------------------


class PayoutItemOut(ApiModel):
    order_id: uuid.UUID
    amount: Decimal
    commission_amount: Decimal


class PayoutOut(ApiModel):
    id: uuid.UUID
    provider_user_id: uuid.UUID
    status: PayoutStatus
    method: PayoutMethod
    amount: Decimal
    batch_id: str | None
    period_start: date | None
    period_end: date | None
    executed_at: datetime | None
    created_at: datetime
    items: list[PayoutItemOut] = []


@router.post("/payouts/build", response_model=list[PayoutOut])
async def build_payouts(staff: CurrentStaff, session: SessionDep) -> list[PayoutOut]:
    """Сформировать реестры по всем оплаченным заказам без выплат."""
    payouts = await payout_service.build_payout_registry(session)
    return [PayoutOut.model_validate(p) for p in payouts]


@router.get("/payouts", response_model=Page[PayoutOut])
async def list_payouts(
    staff: CurrentStaff,
    session: SessionDep,
    pagination: PaginationDep,
    status: PayoutStatus | None = None,
) -> Page[PayoutOut]:
    payouts, total = await payout_service.list_payouts(
        session, status, pagination.limit, pagination.offset
    )
    return Page(
        items=[PayoutOut.model_validate(p) for p in payouts],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("/payouts/{payout_id}/mark-paid", response_model=PayoutOut)
async def mark_paid(
    payout_id: uuid.UUID, staff: CurrentStaff, session: SessionDep
) -> PayoutOut:
    payout = await payout_service.mark_payout_paid(session, staff, payout_id)
    return PayoutOut.model_validate(payout)


# --- Правила отмен (п. 5.3 ТЗ) -------------------------------------------------


class CancellationRuleIn(BaseModel):
    hours_before: int = Field(ge=0, le=720)
    penalty_percent: Decimal = Field(ge=0, le=100)


class CancellationRuleOut(ApiModel):
    id: uuid.UUID
    hours_before: int
    penalty_percent: Decimal
    is_active: bool


@router.get("/cancellation-rules", response_model=list[CancellationRuleOut])
async def get_cancellation_rules(
    staff: CurrentStaff, session: SessionDep
) -> list[CancellationRuleOut]:
    rows = await session.scalars(
        sa.select(CancellationRule).order_by(CancellationRule.hours_before)
    )
    return [CancellationRuleOut.model_validate(r) for r in rows]


@router.put("/cancellation-rules", response_model=list[CancellationRuleOut])
async def set_cancellation_rules(
    items: list[CancellationRuleIn], staff: CurrentStaff, session: SessionDep
) -> list[CancellationRuleOut]:
    """Полная замена набора правил."""
    await session.execute(sa.delete(CancellationRule))
    for item in items:
        session.add(CancellationRule(**item.model_dump()))
    await session.flush()
    rows = await session.scalars(
        sa.select(CancellationRule).order_by(CancellationRule.hours_before)
    )
    return [CancellationRuleOut.model_validate(r) for r in rows]


# --- Тарифы комиссии (п. 5.7 ТЗ) ----------------------------------------------


class CommissionRuleIn(BaseModel):
    # None = глобальное правило для всех категорий.
    category_id: uuid.UUID | None = None
    rate: Decimal = Field(ge=0, le=1, description="Доля: 0.15 = 15%")
    valid_from: date
    valid_until: date | None = None
    comment: str | None = Field(default=None, max_length=255)


class CommissionRuleOut(ApiModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    rate: Decimal
    valid_from: date
    valid_until: date | None
    comment: str | None


@router.get("/commission-rules", response_model=list[CommissionRuleOut])
async def get_commission_rules(
    staff: CurrentStaff, session: SessionDep
) -> list[CommissionRuleOut]:
    rows = await session.scalars(
        sa.select(CommissionRule).order_by(CommissionRule.valid_from.desc())
    )
    return [CommissionRuleOut.model_validate(r) for r in rows]


@router.post("/commission-rules", response_model=CommissionRuleOut, status_code=201)
async def create_commission_rule(
    data: CommissionRuleIn, staff: CurrentStaff, session: SessionDep
) -> CommissionRuleOut:
    if data.valid_until is not None and data.valid_until < data.valid_from:
        raise ConflictError("Дата окончания раньше даты начала")
    rule = CommissionRule(**data.model_dump())
    session.add(rule)
    await session.flush()
    session.add(
        AuditLog(
            actor_id=staff.id,
            action="commission_rule.create",
            entity_type="commission_rule",
            entity_id=rule.id,
            payload={"rate": str(data.rate)},
        )
    )
    return CommissionRuleOut.model_validate(rule)


@router.delete("/commission-rules/{rule_id}", response_model=Ok)
async def delete_commission_rule(
    rule_id: uuid.UUID, staff: CurrentStaff, session: SessionDep
) -> Ok:
    rule = await session.get(CommissionRule, rule_id)
    if rule is None:
        raise NotFoundError("Правило не найдено")
    await session.delete(rule)
    session.add(
        AuditLog(
            actor_id=staff.id,
            action="commission_rule.delete",
            entity_type="commission_rule",
            entity_id=rule_id,
        )
    )
    return Ok()


# --- Промокоды (п. 5.7 ТЗ) -----------------------------------------------------


class PromoCodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=32)
    discount_percent: int | None = Field(default=None, ge=1, le=100)
    discount_amount: Decimal | None = Field(default=None, gt=0)
    max_uses: int | None = Field(default=None, ge=1)
    per_user_limit: int = Field(default=1, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class PromoCodeOut(ApiModel):
    id: uuid.UUID
    code: str
    discount_percent: int | None
    discount_amount: Decimal | None
    max_uses: int | None
    used_count: int
    per_user_limit: int
    valid_from: datetime | None
    valid_until: datetime | None
    is_active: bool


@router.get("/promo-codes", response_model=list[PromoCodeOut])
async def get_promo_codes(staff: CurrentStaff, session: SessionDep) -> list[PromoCodeOut]:
    rows = await session.scalars(sa.select(PromoCode).order_by(PromoCode.created_at.desc()))
    return [PromoCodeOut.model_validate(p) for p in rows]


@router.post("/promo-codes", response_model=PromoCodeOut, status_code=201)
async def create_promo_code(
    data: PromoCodeIn, staff: CurrentStaff, session: SessionDep
) -> PromoCodeOut:
    if (data.discount_percent is None) == (data.discount_amount is None):
        raise ConflictError(
            "Укажите либо процент, либо фиксированную сумму скидки",
            code="invalid_discount",
        )
    code = data.code.strip().upper()
    exists = await session.scalar(sa.select(PromoCode).where(PromoCode.code == code))
    if exists is not None:
        raise ConflictError("Такой промокод уже есть", code="duplicate_code")
    promo = PromoCode(**{**data.model_dump(), "code": code})
    session.add(promo)
    await session.flush()
    return PromoCodeOut.model_validate(promo)


@router.post("/promo-codes/{promo_id}/toggle", response_model=PromoCodeOut)
async def toggle_promo_code(
    promo_id: uuid.UUID, staff: CurrentStaff, session: SessionDep
) -> PromoCodeOut:
    promo = await session.get(PromoCode, promo_id)
    if promo is None:
        raise NotFoundError("Промокод не найден")
    promo.is_active = not promo.is_active
    return PromoCodeOut.model_validate(promo)


# --- Аналитика (п. 5.7 ТЗ) -----------------------------------------------------


@router.get("/stats")
async def stats(staff: CurrentStaff, session: SessionDep) -> dict[str, Any]:
    return await collect_stats(session)


@router.get("/reconciliation")
async def reconciliation(staff: CurrentStaff, session: SessionDep) -> dict[str, Any]:
    """Расхождения между заказами и платежами — для ручного разбора финансистом."""
    return await collect_reconciliation(session)
