"""Тесты гео-эндпоинтов: подсказки, геокодинг, конфиг карты."""

from __future__ import annotations

from typing import Any

from tests.conftest import login


async def test_map_config_without_key(client):
    """Без ключа клиент получает null и покажет заглушку вместо карты."""
    resp = await client.get("/api/v1/geo/config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["map_key"] is None
    # Центр Астаны — город запуска (п. 1.4 ТЗ).
    assert round(body["center_latitude"], 2) == 51.13
    assert round(body["center_longitude"], 2) == 71.43


async def test_geo_requires_auth(client):
    resp = await client.get("/api/v1/geo/suggest?q=Кабанбай")
    assert resp.status_code == 401


async def test_stub_provider_returns_city_center(client):
    """Заглушка без ключа: подсказок нет, геокодинг даёт центр города."""
    headers = await login(client, "+77019990001")

    resp = await client.get("/api/v1/geo/suggest?q=Кабанбай батыра", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []

    resp = await client.get("/api/v1/geo/geocode?q=Кабанбай батыра 53", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert round(body["latitude"], 2) == 51.13

    resp = await client.get("/api/v1/geo/reverse?lat=51.1&lon=71.4", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["latitude"] == 51.1


async def test_dgis_provider_parses_response(client, monkeypatch):
    """Ответ 2GIS разбирается в подсказки; ключ уходит в запрос, но не наружу."""
    from app.services import geo as geo_module

    captured: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "result": {
                    "items": [
                        {
                            "id": "141373143530064",
                            "name": "Кабанбай батыра, 53",
                            "full_name": "Астана, Кабанбай батыра просп., 53",
                            "point": {"lat": 51.0899, "lon": 71.4181},
                        }
                    ]
                }
            }

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, params: dict[str, Any]) -> FakeResponse:
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr(geo_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(geo_module.settings, "dgis_catalog_key", "test-catalog-key")
    monkeypatch.setattr(geo_module, "_provider", geo_module.DgisGeoProvider())

    headers = await login(client, "+77019990002")
    resp = await client.get(
        "/api/v1/geo/suggest?q=Кабанбай&lat=51.13&lon=71.43", headers=headers
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["full_name"] == "Астана, Кабанбай батыра просп., 53"
    assert items[0]["latitude"] == 51.0899

    # Ключ ушёл в 2GIS, координаты — в порядке "lon,lat", как требует их API.
    assert captured["params"]["key"] == "test-catalog-key"
    assert captured["params"]["location"] == "71.43,51.13"
    assert captured["url"].endswith("/items")

    # Наружу ключ не отдаётся.
    assert "test-catalog-key" not in resp.text


async def test_dgis_failure_does_not_break_client(client, monkeypatch):
    """Недоступность 2GIS не роняет запрос — возвращается пустой результат."""
    from app.services import geo as geo_module

    class BrokenClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> BrokenClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, params: dict[str, Any]) -> None:
            raise TimeoutError("2GIS недоступен")

    monkeypatch.setattr(geo_module.httpx, "AsyncClient", BrokenClient)
    monkeypatch.setattr(geo_module.settings, "dgis_catalog_key", "test-catalog-key")
    monkeypatch.setattr(geo_module, "_provider", geo_module.DgisGeoProvider())

    headers = await login(client, "+77019990003")
    resp = await client.get("/api/v1/geo/suggest?q=Кабанбай", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []
