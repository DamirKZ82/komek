"""Верификация исполнителей и разбор жалоб (разделы 4 и 5.7 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models.enums import (
    ComplaintCategory,
    ComplaintStatus,
    ProviderStatus,
    UserStatus,
    VerificationLevel,
    VerificationRequestStatus,
)
from app.models.moderation import AuditLog, Complaint
from app.models.provider import ProviderProfile
from app.models.user import User
from app.models.verification import VerificationRequest
from app.schemas.moderation import ComplaintIn, ComplaintResolveIn, VerificationDecisionIn
from app.services.notifications import notify_user

_OPEN_STATUSES = (
    VerificationRequestStatus.SUBMITTED,
    VerificationRequestStatus.IN_REVIEW,
)


async def submit_verification(
    session: AsyncSession, user: User, target_level: VerificationLevel
) -> VerificationRequest:
    profile = await session.get(ProviderProfile, user.id)
    if profile is None:
        raise NotFoundError("Профиль исполнителя не найден")
    if profile.verification_level.rank >= target_level.rank:
        raise ConflictError("Этот уровень уже подтверждён", code="level_already_granted")

    existing = await session.scalar(
        sa.select(VerificationRequest).where(
            VerificationRequest.user_id == user.id,
            VerificationRequest.status.in_(_OPEN_STATUSES),
        )
    )
    if existing is not None:
        raise ConflictError("Заявка уже на рассмотрении", code="request_pending")

    request = VerificationRequest(user_id=user.id, target_level=target_level)
    session.add(request)
    # Анкета уходит в очередь модерации.
    if profile.status in (ProviderStatus.DRAFT, ProviderStatus.REJECTED):
        profile.status = ProviderStatus.PENDING_REVIEW
    await session.flush()
    return request


async def my_verification_request(
    session: AsyncSession, user: User
) -> VerificationRequest | None:
    return await session.scalar(
        sa.select(VerificationRequest)
        .where(VerificationRequest.user_id == user.id)
        .order_by(VerificationRequest.submitted_at.desc())
        .limit(1)
    )


async def decide_verification(
    session: AsyncSession,
    moderator: User,
    request_id: uuid.UUID,
    data: VerificationDecisionIn,
) -> VerificationRequest:
    request = await session.get(VerificationRequest, request_id, with_for_update=True)
    if request is None:
        raise NotFoundError("Заявка не найдена")
    if request.status not in _OPEN_STATUSES:
        raise ConflictError("Заявка уже рассмотрена", code="already_decided")

    profile = await session.get(ProviderProfile, request.user_id)
    if profile is None:
        raise NotFoundError("Профиль исполнителя не найден")

    now = datetime.now(UTC)
    request.assigned_to_id = moderator.id
    request.decided_at = now
    request.checklist = data.checklist
    request.moderator_notes = data.notes

    if data.approve:
        request.status = VerificationRequestStatus.APPROVED
        profile.verification_level = request.target_level
        profile.verification_level_updated_at = now
        # Уровень 2+ открывает анкету в поиске (п. 4.1 ТЗ).
        if request.target_level.rank >= 2:
            profile.status = ProviderStatus.ACTIVE
    else:
        if not data.rejection_reason:
            raise ConflictError("Укажите причину отказа", code="reason_required")
        request.status = VerificationRequestStatus.REJECTED
        request.rejection_reason = data.rejection_reason
        profile.status = ProviderStatus.REJECTED

    session.add(
        AuditLog(
            actor_id=moderator.id,
            action="verification.approve" if data.approve else "verification.reject",
            entity_type="verification_request",
            entity_id=request.id,
            payload={"target_level": request.target_level.value, "checklist": data.checklist},
        )
    )
    if data.approve:
        await notify_user(
            session,
            request.user_id,
            "Проверка пройдена",
            "Ваша анкета одобрена и видна в поиске",
        )
    else:
        await notify_user(
            session,
            request.user_id,
            "Анкета отклонена",
            data.rejection_reason or "Проверьте замечания модератора",
        )
    return request


# --- Жалобы -------------------------------------------------------------------


async def file_complaint(session: AsyncSession, reporter: User, data: ComplaintIn) -> Complaint:
    complaint = Complaint(
        reporter_id=reporter.id,
        target_user_id=data.target_user_id,
        order_id=data.order_id,
        category=data.category,
        description=data.description,
    )
    session.add(complaint)

    # Категория «безопасность»: автоматическая приостановка профиля до разбора (п. 4.4 ТЗ).
    if data.category == ComplaintCategory.SAFETY and data.target_user_id is not None:
        profile = await session.get(ProviderProfile, data.target_user_id)
        if profile is not None and profile.status == ProviderStatus.ACTIVE:
            profile.status = ProviderStatus.SUSPENDED
            complaint.auto_suspended = True
    await session.flush()
    return complaint


async def resolve_complaint(
    session: AsyncSession, moderator: User, complaint_id: uuid.UUID, data: ComplaintResolveIn
) -> Complaint:
    complaint = await session.get(Complaint, complaint_id, with_for_update=True)
    if complaint is None:
        raise NotFoundError("Жалоба не найдена")
    if complaint.status in (ComplaintStatus.RESOLVED, ComplaintStatus.DISMISSED):
        raise ConflictError("Жалоба уже закрыта", code="already_resolved")

    complaint.status = (
        ComplaintStatus.DISMISSED if data.dismiss else ComplaintStatus.RESOLVED
    )
    complaint.assigned_to_id = moderator.id
    complaint.resolution = data.resolution
    complaint.compensation_amount = data.compensation_amount
    complaint.resolved_at = datetime.now(UTC)

    # Если профиль был приостановлен автоматически и жалоба отклонена — возвращаем в поиск.
    if complaint.auto_suspended and data.dismiss and complaint.target_user_id is not None:
        profile = await session.get(ProviderProfile, complaint.target_user_id)
        if profile is not None and profile.status == ProviderStatus.SUSPENDED:
            profile.status = ProviderStatus.ACTIVE

    session.add(
        AuditLog(
            actor_id=moderator.id,
            action="complaint.dismiss" if data.dismiss else "complaint.resolve",
            entity_type="complaint",
            entity_id=complaint.id,
            payload={"category": complaint.category.value},
        )
    )
    return complaint


async def suspend_user(
    session: AsyncSession, moderator: User, user_id: uuid.UUID, reason: str
) -> User:
    """Ручная блокировка аккаунта модератором."""
    target = await session.get(User, user_id)
    if target is None:
        raise NotFoundError("Пользователь не найден")
    target.status = UserStatus.SUSPENDED
    target.suspended_reason = reason
    profile = await session.get(ProviderProfile, user_id)
    if profile is not None and profile.status == ProviderStatus.ACTIVE:
        profile.status = ProviderStatus.SUSPENDED
    session.add(
        AuditLog(
            actor_id=moderator.id,
            action="user.suspend",
            entity_type="user",
            entity_id=user_id,
            payload={"reason": reason},
        )
    )
    return target
