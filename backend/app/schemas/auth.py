from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import Locale


class OtpRequestIn(BaseModel):
    phone: str = Field(examples=["+77011234567"])


class OtpRequestOut(BaseModel):
    expires_in: int
    resend_after: int
    # Возвращается только вне production — чтобы тестировать вход без реальной SMS.
    debug_code: str | None = None


class OtpVerifyIn(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=8)
    locale: Locale = Locale.RU


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    is_new_user: bool = False


class RefreshIn(BaseModel):
    refresh_token: str
