"""Подтверждение личности (п. 4.1 уровень 1, п. 4.3 ТЗ).

Заказчику даёт значок «проверенный заказчик»; исполнителю — уровень 1 и
ИИН для сверки со справками (шаг 4 флоу верификации, п. 4.2 ТЗ).

Ключевое: результат берётся из сессии KYC, подтверждённой провайдером.
Клиент не может объявить себя проверенным — он лишь запускает сессию.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.enums import ConsentType, KycSessionStatus, VerificationLevel
from app.models.kyc import KycSession
from app.models.provider import ProviderProfile
from app.models.user import User, UserConsent
from app.services.kyc import KycResult, get_kyc_provider


def _age(birth_date: date, today: date) -> int:
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


async def start_session(session: AsyncSession, user: User) -> KycSession:
    """Создаёт сессию проверки у провайдера для запуска мобильного SDK."""
    if user.identity_verified_at is not None:
        raise ConflictError("Личность уже подтверждена", code="already_verified")

    provider = get_kyc_provider()
    init = await provider.create_session(str(user.id))

    kyc_session = KycSession(
        user_id=user.id,
        provider=provider.name,
        provider_session_id=init.session_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.kyc_session_ttl_minutes),
    )
    session.add(kyc_session)
    await session.flush()
    # Токен SDK не храним: он одноразовый и нужен только клиенту.
    kyc_session.payload = {"client_token": init.client_token, "sdk_url": init.sdk_url}
    return kyc_session


async def apply_result(
    session: AsyncSession, kyc_session: KycSession, result: KycResult
) -> KycSession:
    """Сохраняет исход проверки в сессию (вызывается вебхуком и опросом)."""
    kyc_session.status = result.status
    kyc_session.failure_reason = result.reason
    if result.iin:
        kyc_session.iin = result.iin
    if result.first_name:
        kyc_session.first_name = result.first_name
    if result.last_name:
        kyc_session.last_name = result.last_name
    if result.birth_date:
        kyc_session.birth_date = result.birth_date
    if result.payload:
        kyc_session.payload = result.payload
    if result.status in (KycSessionStatus.PASSED, KycSessionStatus.FAILED):
        kyc_session.completed_at = datetime.now(UTC)
    return kyc_session


async def confirm_identity(
    session: AsyncSession, user: User, session_id: uuid.UUID, ip: str | None = None
) -> User:
    """Подтверждает личность по успешной сессии KYC."""
    kyc_session = await session.get(KycSession, session_id, with_for_update=True)
    if kyc_session is None or kyc_session.user_id != user.id:
        raise NotFoundError("Сессия проверки не найдена")
    if user.identity_verified_at is not None:
        raise ConflictError("Личность уже подтверждена", code="already_verified")
    if kyc_session.consumed_at is not None:
        raise ConflictError("Сессия уже использована", code="session_consumed")

    now = datetime.now(UTC)
    expires_at = kyc_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if now > expires_at:
        kyc_session.status = KycSessionStatus.EXPIRED
        raise ConflictError("Срок сессии истёк, начните заново", code="session_expired")

    # Результат мог ещё не прийти вебхуком — спрашиваем провайдера напрямую.
    if kyc_session.status in (KycSessionStatus.CREATED, KycSessionStatus.PENDING):
        result = await get_kyc_provider().fetch_result(kyc_session.provider_session_id)
        await apply_result(session, kyc_session, result)

    if kyc_session.status != KycSessionStatus.PASSED:
        raise ForbiddenError(
            kyc_session.failure_reason or "Проверка личности не пройдена", code="kyc_failed"
        )

    # Один и тот же человек не должен заводить два аккаунта на один ИИН.
    if kyc_session.iin:
        duplicate = await session.scalar(
            sa.select(User).where(User.iin_encrypted == kyc_session.iin, User.id != user.id)
        )
        if duplicate is not None:
            raise ConflictError(
                "Этот ИИН уже привязан к другому аккаунту", code="iin_already_used"
            )

    if kyc_session.first_name and not user.first_name:
        user.first_name = kyc_session.first_name
    if kyc_session.last_name and not user.last_name:
        user.last_name = kyc_session.last_name
    if kyc_session.birth_date:
        # Формат даты у провайдера может отличаться — некорректную игнорируем.
        with suppress(ValueError):
            user.birth_date = date.fromisoformat(kyc_session.birth_date)

    # Возрастной ценз применяем только к исполнителям (п. 4.1 ТЗ).
    profile = await session.get(ProviderProfile, user.id)
    if (
        profile is not None
        and user.birth_date is not None
        and _age(user.birth_date, now.date()) < settings.min_provider_age
    ):
        raise ForbiddenError(
            f"Исполнителем можно стать с {settings.min_provider_age} лет", code="underage"
        )

    if kyc_session.iin:
        # TODO(security): шифровать на уровне приложения перед записью.
        user.iin_encrypted = kyc_session.iin
    user.identity_verified_at = now
    kyc_session.consumed_at = now

    session.add(
        UserConsent(
            user_id=user.id,
            consent_type=ConsentType.PERSONAL_DATA,
            document_version="1.0",
            ip_address=ip,
        )
    )

    # Для исполнителя это уровень 1 «Личность подтверждена».
    if profile is not None and profile.verification_level == VerificationLevel.REGISTERED:
        profile.verification_level = VerificationLevel.IDENTITY
        profile.verification_level_updated_at = now

    return user
