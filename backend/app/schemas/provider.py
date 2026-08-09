from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import (
    Language,
    LanguageLevel,
    PriceUnit,
    ProviderStatus,
    VerificationLevel,
)
from app.schemas.common import ApiModel


class ProviderServiceIn(BaseModel):
    service_id: uuid.UUID
    price: Decimal = Field(gt=0)
    price_unit: PriceUnit = PriceUnit.HOUR
    min_duration_minutes: int | None = None
    is_active: bool = True


class ProviderServiceOut(ApiModel):
    id: uuid.UUID
    service_id: uuid.UUID
    service_code: str | None = None
    service_name: str | None = None
    price: Decimal
    price_unit: PriceUnit
    min_duration_minutes: int | None
    is_active: bool


class ProviderLanguageIn(BaseModel):
    language: Language
    level: LanguageLevel = LanguageLevel.CONVERSATIONAL


class ProviderProfileUpdateIn(BaseModel):
    headline: str | None = Field(default=None, max_length=160)
    about: str | None = None
    experience_years: int | None = Field(default=None, ge=0, le=60)
    education: str | None = None
    city_id: uuid.UUID | None = None
    base_latitude: float | None = None
    base_longitude: float | None = None
    work_radius_km: int | None = Field(default=None, ge=1, le=100)
    accepts_urgent: bool | None = None
    accepts_live_in: bool | None = None
    has_car: bool | None = None
    is_non_smoker: bool | None = None
    district_ids: list[uuid.UUID] | None = None
    qualification_ids: list[uuid.UUID] | None = None
    languages: list[ProviderLanguageIn] | None = None


class ProviderCard(BaseModel):
    """Карточка в выдаче поиска (п. 5.1 ТЗ)."""

    user_id: uuid.UUID
    first_name: str | None
    last_name: str | None
    avatar_key: str | None
    headline: str | None
    verification_level: VerificationLevel
    experience_years: int
    rating_avg: Decimal | None
    rating_count: int
    completed_orders_count: int
    response_time_minutes: int | None
    min_price: Decimal | None
    price_unit: PriceUnit | None
    accepts_urgent: bool
    # Базовая точка для отображения на карте (п. 6 ТЗ). Точный адрес не раскрываем.
    base_latitude: float | None = None
    base_longitude: float | None = None
    languages: list[Language] = []
    is_favorite: bool = False


class ProviderDetail(ProviderCard):
    about: str | None
    education: str | None
    video_key: str | None
    status: ProviderStatus
    work_radius_km: int
    accepts_live_in: bool
    has_car: bool
    is_non_smoker: bool
    # Наружу отдаём только факт и срок действия проверок — сами документы закрыты (п. 4.2 ТЗ).
    documents_valid_until: date | None
    verification_level_updated_at: datetime | None
    services: list[ProviderServiceOut] = []
    qualification_ids: list[uuid.UUID] = []
    district_ids: list[uuid.UUID] = []


class WeeklySlotIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    time_from: time
    time_to: time


class WeeklySlotOut(ApiModel):
    id: uuid.UUID
    weekday: int
    time_from: time
    time_to: time
