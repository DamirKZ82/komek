"""JWT-токены и хеширование одноразовых кодов."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Токен отсутствует, повреждён или истёк."""


def _create_token(subject: UUID, token_type: TokenType, ttl: timedelta, **claims: Any) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": secrets.token_urlsafe(16),
        **claims,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID, **claims: Any) -> str:
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_ttl_minutes), **claims
    )


def create_refresh_token(user_id: UUID) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_ttl_days))


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Срок действия токена истёк") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Некорректный токен") from exc

    if payload.get("typ") != expected_type:
        raise TokenError("Неподходящий тип токена")
    return payload


# --- Одноразовые коды ---------------------------------------------------------


def generate_otp_code() -> str:
    """В local/staging возвращает фиксированный код, чтобы не жечь SMS на тестах."""
    if settings.otp_debug_code and not settings.is_production:
        return settings.otp_debug_code
    upper = 10**settings.otp_length
    return str(secrets.randbelow(upper)).zfill(settings.otp_length)


def hash_otp_code(phone: str, code: str) -> str:
    """Коды в БД хранятся только в виде HMAC — открытый код не восстанавливается."""
    message = f"{phone}:{code}".encode()
    return hmac.new(settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()


def verify_otp_code(phone: str, code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp_code(phone, code), code_hash)
