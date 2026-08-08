from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.errors import AuthError
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.models.user import User
from app.schemas.auth import OtpRequestIn, OtpRequestOut, OtpVerifyIn, RefreshIn, TokenPair
from app.services import auth as auth_service
from app.services.phone import normalize_phone

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request", response_model=OtpRequestOut)
async def request_otp(data: OtpRequestIn, session: SessionDep, request: Request) -> OtpRequestOut:
    phone = normalize_phone(data.phone)
    client_ip = request.client.host if request.client else None
    return await auth_service.request_otp(session, phone, client_ip)


@router.post("/otp/verify", response_model=TokenPair)
async def verify_otp(data: OtpVerifyIn, session: SessionDep) -> TokenPair:
    phone = normalize_phone(data.phone)
    return await auth_service.verify_otp(session, phone, data.code, data.locale)


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(data: RefreshIn, session: SessionDep) -> TokenPair:
    try:
        payload = decode_token(data.refresh_token, "refresh")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise AuthError()
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.access_token_ttl_minutes * 60,
    )
