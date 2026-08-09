"""Вход по номеру телефона: запрос кода → проверка → JWT-пара."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, RateLimitError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_otp_code,
    hash_otp_code,
    verify_otp_code,
)
from app.models.enums import Locale, OtpPurpose
from app.models.user import OtpCode, User
from app.schemas.auth import OtpRequestOut, TokenPair
from app.services.sms import send_sms


class InvalidOtpError(AppError):
    code = "invalid_otp"
    message = "Неверный или просроченный код"


async def request_otp(session: AsyncSession, phone: str, ip: str | None) -> OtpRequestOut:
    now = datetime.now(UTC)

    # Кулдаун на повторную отправку.
    recent = await session.scalar(
        sa.select(OtpCode)
        .where(
            OtpCode.phone == phone,
            OtpCode.purpose == OtpPurpose.LOGIN,
            OtpCode.consumed_at.is_(None),
            OtpCode.created_at > now - timedelta(seconds=settings.otp_resend_cooldown_seconds),
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if recent is not None:
        raise RateLimitError("Код уже отправлен, подождите минуту")

    # Не больше 5 кодов в час на номер.
    hour_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.created_at > now - timedelta(hours=1))
    )
    if (hour_count or 0) >= 5:
        raise RateLimitError()

    code = generate_otp_code()
    session.add(
        OtpCode(
            phone=phone,
            purpose=OtpPurpose.LOGIN,
            code_hash=hash_otp_code(phone, code),
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
            ip_address=ip,
        )
    )
    await send_sms(
        phone, f"Komek: код подтверждения {code}", session=session, purpose="otp"
    )

    return OtpRequestOut(
        expires_in=settings.otp_ttl_seconds,
        resend_after=settings.otp_resend_cooldown_seconds,
        debug_code=None if settings.is_production else code,
    )


async def verify_otp(
    session: AsyncSession, phone: str, code: str, locale: Locale
) -> TokenPair:
    now = datetime.now(UTC)
    otp = await session.scalar(
        sa.select(OtpCode)
        .where(
            OtpCode.phone == phone,
            OtpCode.purpose == OtpPurpose.LOGIN,
            OtpCode.consumed_at.is_(None),
            OtpCode.expires_at > now,
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp is None:
        raise InvalidOtpError()
    if otp.attempts >= settings.otp_max_attempts:
        raise RateLimitError("Код заблокирован, запросите новый")

    otp.attempts += 1
    if not verify_otp_code(phone, code, otp.code_hash):
        raise InvalidOtpError()

    otp.consumed_at = now

    user = await session.scalar(sa.select(User).where(User.phone == phone))
    is_new = user is None
    if user is None:
        user = User(phone=phone, phone_verified_at=now, locale=locale)
        session.add(user)
        await session.flush()  # получаем user.id
    else:
        user.phone_verified_at = user.phone_verified_at or now
        user.last_seen_at = now

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.access_token_ttl_minutes * 60,
        is_new_user=is_new,
    )
