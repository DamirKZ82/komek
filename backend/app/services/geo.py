"""Гео-сервисы 2GIS (п. 6 ТЗ: карты и геокодинг — приоритет 2GIS для КЗ).

Ключ каталога живёт только на сервере: приложение ходит через наши эндпоинты,
поэтому ключ не попадает в клиент и его нельзя вытащить из APK.
(Ключ MapGL — отдельный, он по своей природе публичный и ограничивается
доменом/приложением в Platform Manager.)

Без DGIS_CATALOG_KEY работает заглушка: подсказки не выдаются, геокодинг
возвращает центр города. Это позволяет разрабатывать и тестировать без ключа.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger("komek.geo")

CATALOG_BASE_URL = "https://catalog.api.2gis.com/3.0"


@dataclass(slots=True)
class GeoPoint:
    latitude: float
    longitude: float


@dataclass(slots=True)
class AddressSuggestion:
    """Подсказка адреса. `full_name` — то, что показываем пользователю."""

    id: str | None
    name: str
    full_name: str
    latitude: float | None = None
    longitude: float | None = None


class GeoProvider(Protocol):
    async def suggest(
        self, query: str, near: GeoPoint | None = None, limit: int = 10
    ) -> list[AddressSuggestion]: ...

    async def geocode(
        self, query: str, near: GeoPoint | None = None
    ) -> AddressSuggestion | None: ...

    async def reverse(self, point: GeoPoint) -> AddressSuggestion | None: ...


class StubGeoProvider:
    """Разработка без ключа: подсказок нет, координаты — центр города запуска."""

    async def suggest(
        self, query: str, near: GeoPoint | None = None, limit: int = 10
    ) -> list[AddressSuggestion]:
        return []

    async def geocode(self, query: str, near: GeoPoint | None = None) -> AddressSuggestion | None:
        return AddressSuggestion(
            id=None,
            name=query,
            full_name=query,
            latitude=settings.default_city_latitude,
            longitude=settings.default_city_longitude,
        )

    async def reverse(self, point: GeoPoint) -> AddressSuggestion | None:
        return AddressSuggestion(
            id=None,
            name=f"{point.latitude:.5f}, {point.longitude:.5f}",
            full_name=f"{point.latitude:.5f}, {point.longitude:.5f}",
            latitude=point.latitude,
            longitude=point.longitude,
        )


def _parse_item(item: dict[str, Any]) -> AddressSuggestion:
    point = item.get("point") or {}
    return AddressSuggestion(
        id=item.get("id"),
        name=item.get("name") or item.get("full_name") or "",
        full_name=item.get("full_name") or item.get("name") or "",
        latitude=point.get("lat"),
        longitude=point.get("lon"),
    )


class DgisGeoProvider:
    """2GIS Catalog API: Suggest для подсказок, Geocoder для координат и адресов."""

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{CATALOG_BASE_URL}{path}",
                    params={**params, "key": settings.dgis_catalog_key},
                )
                response.raise_for_status()
                return response.json()
        except Exception:  # noqa: BLE001 — гео не должно ронять основной сценарий
            logger.warning("2GIS недоступен: %s", path, exc_info=True)
            return None

    async def suggest(
        self, query: str, near: GeoPoint | None = None, limit: int = 10
    ) -> list[AddressSuggestion]:
        params: dict[str, Any] = {
            "q": query,
            "suggest_type": "address",
            "fields": "items.point,items.full_name",
            "page_size": min(limit, 20),
        }
        if near is not None:
            # 2GIS ждёт "lon,lat" — порядок обратный привычному.
            params["location"] = f"{near.longitude},{near.latitude}"
        data = await self._get("/items", params)
        items = ((data or {}).get("result") or {}).get("items") or []
        return [_parse_item(item) for item in items]

    async def geocode(self, query: str, near: GeoPoint | None = None) -> AddressSuggestion | None:
        params: dict[str, Any] = {"q": query, "fields": "items.point,items.full_name"}
        if near is not None:
            params["location"] = f"{near.longitude},{near.latitude}"
        data = await self._get("/items/geocode", params)
        items = ((data or {}).get("result") or {}).get("items") or []
        return _parse_item(items[0]) if items else None

    async def reverse(self, point: GeoPoint) -> AddressSuggestion | None:
        data = await self._get(
            "/items/geocode",
            {
                "lat": point.latitude,
                "lon": point.longitude,
                "fields": "items.point,items.full_name",
            },
        )
        items = ((data or {}).get("result") or {}).get("items") or []
        return _parse_item(items[0]) if items else None


_provider: GeoProvider | None = None


def get_geo_provider() -> GeoProvider:
    global _provider
    if _provider is None:
        _provider = DgisGeoProvider() if settings.dgis_catalog_key else StubGeoProvider()
    return _provider
