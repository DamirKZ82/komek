"""Гео-эндпоинты: подсказки адресов и геокодинг через 2GIS (п. 5.1, 6 ТЗ)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep  # noqa: F401 — SessionDep для будущего кэша
from app.core.config import settings
from app.services.geo import AddressSuggestion, GeoPoint, get_geo_provider

router = APIRouter(prefix="/geo", tags=["geo"])


class SuggestionOut(BaseModel):
    id: str | None
    name: str
    full_name: str
    latitude: float | None
    longitude: float | None

    @classmethod
    def of(cls, item: AddressSuggestion) -> SuggestionOut:
        return cls(
            id=item.id,
            name=item.name,
            full_name=item.full_name,
            latitude=item.latitude,
            longitude=item.longitude,
        )


class MapConfigOut(BaseModel):
    """Настройки карты для клиента. Ключ MapGL публичный по своей природе."""

    map_key: str | None
    center_latitude: float
    center_longitude: float


@router.get("/config", response_model=MapConfigOut)
async def map_config() -> MapConfigOut:
    return MapConfigOut(
        map_key=settings.dgis_map_key,
        center_latitude=settings.default_city_latitude,
        center_longitude=settings.default_city_longitude,
    )


@router.get("/suggest", response_model=list[SuggestionOut])
async def suggest_address(
    user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    lat: float | None = None,
    lon: float | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> list[SuggestionOut]:
    """Подсказки адресов по мере ввода."""
    near = GeoPoint(latitude=lat, longitude=lon) if lat is not None and lon is not None else None
    items = await get_geo_provider().suggest(q, near, limit)
    return [SuggestionOut.of(item) for item in items]


@router.get("/geocode", response_model=SuggestionOut | None)
async def geocode(
    user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    lat: float | None = None,
    lon: float | None = None,
) -> SuggestionOut | None:
    """Адрес → координаты."""
    near = GeoPoint(latitude=lat, longitude=lon) if lat is not None and lon is not None else None
    item = await get_geo_provider().geocode(q, near)
    return SuggestionOut.of(item) if item else None


@router.get("/reverse", response_model=SuggestionOut | None)
async def reverse_geocode(
    user: CurrentUser,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> SuggestionOut | None:
    """Координаты → адрес: пользователь ставит точку на карте, получает адрес."""
    item = await get_geo_provider().reverse(GeoPoint(latitude=lat, longitude=lon))
    return SuggestionOut.of(item) if item else None
