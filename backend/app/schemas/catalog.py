from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.models.enums import Locale, Vertical


class Localized(BaseModel):
    """Справочники отдают уже выбранный по локали текст — клиенту не нужно знать про ru/kk."""

    @staticmethod
    def pick(obj: object, field: str, locale: Locale) -> str:
        value = getattr(obj, f"{field}_{locale.value}", None)
        return value or getattr(obj, f"{field}_ru")


class CityOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    latitude: float
    longitude: float
    is_active: bool


class DistrictOut(BaseModel):
    id: uuid.UUID
    city_id: uuid.UUID
    code: str
    name: str


class ServiceOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    allowed_price_units: list[str]
    min_duration_minutes: int
    supports_urgent: bool
    required_verification_rank: int


class CategoryOut(BaseModel):
    id: uuid.UUID
    code: str
    vertical: Vertical
    name: str
    icon: str | None = None
    services: list[ServiceOut] = []


class QualificationOut(BaseModel):
    id: uuid.UUID
    code: str
    vertical: Vertical | None
    name: str
    requires_document: bool
