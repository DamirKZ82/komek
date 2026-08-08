"""Подтверждение личности пользователя (п. 4.1 уровень 1, п. 4.3 ТЗ).

Заказчику даёт значок «проверенный заказчик»; исполнителю — уровень 1 и
ИИН для сверки со справками (шаг 4 флоу верификации, п. 4.2 ТЗ).
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.models.enums import ConsentType, VerificationLevel
from app.models.provider import ProviderProfile
from app.models.user import User, UserConsent
from app.services.kyc import get_kyc_provider


def _age(birth_date: date, today: date) -> int:
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


async def verify_identity(
    session: AsyncSession, user: User, session_token: str, ip: str | None = None
) -> User:
    """Обменивает сессию KYC на подтверждение личности."""
    if settings.is_production and not settings.kyc_api_url:
        # Заглушка в проде подтверждала бы личность без проверки — это дыра.
        raise AppError(
            "Проверка личности временно недоступна", code="kyc_not_configured", status_code=503
        )
    if user.identity_verified_at is not None:
        raise ConflictError("Личность уже подтверждена", code="already_verified")

    result = await get_kyc_provider().check_session(session_token)
    if not result.passed:
        raise ForbiddenError(
            result.reason or "Проверка личности не пройдена", code="kyc_failed"
        )

    now = datetime.now(UTC)
    if result.first_name and not user.first_name:
        user.first_name = result.first_name
    if result.last_name and not user.last_name:
        user.last_name = result.last_name
    if result.birth_date:
        # Формат даты у провайдера может отличаться — некорректную просто игнорируем.
        with suppress(ValueError):
            user.birth_date = date.fromisoformat(result.birth_date)

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

    if result.iin:
        # TODO(security): шифровать на уровне приложения перед записью.
        user.iin_encrypted = result.iin
    user.identity_verified_at = now

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
