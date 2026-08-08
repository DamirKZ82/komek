from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import ConsentType, Gender, Locale, StaffRole, UserStatus
from app.schemas.common import ApiModel


class UserOut(ApiModel):
    id: uuid.UUID
    phone: str
    first_name: str | None = None
    last_name: str | None = None
    birth_date: date | None = None
    gender: Gender | None = None
    avatar_key: str | None = None
    locale: Locale
    city_id: uuid.UUID | None = None
    is_customer: bool
    is_provider: bool
    staff_role: StaffRole | None = None
    status: UserStatus
    identity_verified_at: datetime | None = None
    created_at: datetime


class UserUpdateIn(BaseModel):
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    birth_date: date | None = None
    gender: Gender | None = None
    locale: Locale | None = None
    city_id: uuid.UUID | None = None
    email: str | None = None


class ConsentIn(BaseModel):
    consent_type: ConsentType
    document_version: str = "1.0"


class AddressIn(BaseModel):
    label: str | None = Field(default=None, max_length=64)
    city_id: uuid.UUID | None = None
    district_id: uuid.UUID | None = None
    street: str = Field(max_length=255)
    building: str | None = None
    apartment: str | None = None
    entrance: str | None = None
    intercom: str | None = None
    comment: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_default: bool = False


class AddressOut(ApiModel):
    id: uuid.UUID
    label: str | None
    city_id: uuid.UUID | None
    district_id: uuid.UUID | None
    street: str
    building: str | None
    apartment: str | None
    entrance: str | None
    comment: str | None
    latitude: float | None
    longitude: float | None
    is_default: bool
