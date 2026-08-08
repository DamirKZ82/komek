"""Тесты избранного, тарифов комиссии, промокодов и SMS-фолбэка."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa

from tests.conftest import login
from tests.test_chat_moderation import _make_staff


async def _active_provider(client, session_factory, phone: str, price: str = "2000"):
    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    headers = await login(client, phone)
    await client.post("/api/v1/providers/me", headers=headers)
    user_id = (await client.get("/api/v1/me", headers=headers)).json()["id"]
    categories = (await client.get("/api/v1/catalog/categories")).json()
    service = next(
        s for c in categories for s in c["services"] if s["code"] == "babysitter_hourly"
    )
    await client.put(
        "/api/v1/providers/me/services",
        headers=headers,
        json=[{"service_id": service["id"], "price": price, "price_unit": "hour"}],
    )
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()
    return headers, user_id, service["id"]


async def test_favorites_list(client, session_factory):
    _, provider_id, _ = await _active_provider(client, session_factory, "+77016660001")
    customer = await login(client, "+77016660002")

    # Пусто до добавления.
    resp = await client.get("/api/v1/providers/favorites", headers=customer)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []

    resp = await client.put(f"/api/v1/providers/{provider_id}/favorite", headers=customer)
    assert resp.status_code == 200

    resp = await client.get("/api/v1/providers/favorites", headers=customer)
    favorites = resp.json()
    assert len(favorites) == 1
    assert favorites[0]["user_id"] == provider_id
    assert favorites[0]["is_favorite"] is True
    assert favorites[0]["min_price"] == "2000.00"

    # Карточка исполнителя тоже отмечена избранной.
    resp = await client.get(f"/api/v1/providers/{provider_id}", headers=customer)
    assert resp.json()["is_favorite"] is True

    resp = await client.delete(f"/api/v1/providers/{provider_id}/favorite", headers=customer)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/providers/favorites", headers=customer)
    assert resp.json() == []


async def test_commission_rule_applies_to_new_order(client, session_factory):
    """Ставка из админки перекрывает значение по умолчанию для новых заказов."""
    _, provider_id, service_id = await _active_provider(client, session_factory, "+77016660003")
    customer = await login(client, "+77016660004")

    moderator = await login(client, "+77016660005")
    await _make_staff(session_factory, "+77016660005")

    resp = await client.post(
        "/api/v1/admin/commission-rules",
        headers=moderator,
        json={"rate": "0.1", "valid_from": date.today().isoformat(), "comment": "акция"},
    )
    assert resp.status_code == 201, resp.text

    start = datetime.now(UTC) + timedelta(days=2)
    resp = await client.post(
        "/api/v1/orders",
        headers=customer,
        json={
            "service_id": service_id,
            "provider_user_id": provider_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=2)).isoformat(),
            "price_unit": "hour",
        },
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["commission_rate"]) == Decimal("0.1")

    # Удаление правила возвращает ставку по умолчанию (15%).
    rules = (await client.get("/api/v1/admin/commission-rules", headers=moderator)).json()
    await client.delete(f"/api/v1/admin/commission-rules/{rules[0]['id']}", headers=moderator)
    resp = await client.post(
        "/api/v1/orders",
        headers=customer,
        json={
            "service_id": service_id,
            "provider_user_id": provider_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=2)).isoformat(),
            "price_unit": "hour",
        },
    )
    assert Decimal(resp.json()["commission_rate"]) == Decimal("0.15")


async def test_promo_codes_crud(client, session_factory):
    moderator = await login(client, "+77016660006")
    await _make_staff(session_factory, "+77016660006")

    # Нельзя задать одновременно процент и сумму (или не задать ничего).
    resp = await client.post(
        "/api/v1/admin/promo-codes",
        headers=moderator,
        json={"code": "spring", "discount_percent": 10, "discount_amount": "500"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_discount"

    resp = await client.post(
        "/api/v1/admin/promo-codes",
        headers=moderator,
        json={"code": "spring", "discount_percent": 10},
    )
    assert resp.status_code == 201, resp.text
    promo = resp.json()
    assert promo["code"] == "SPRING"  # нормализуется в верхний регистр
    assert promo["is_active"] is True

    # Дубликат отклоняется.
    resp = await client.post(
        "/api/v1/admin/promo-codes",
        headers=moderator,
        json={"code": "SPRING", "discount_percent": 20},
    )
    assert resp.status_code == 409

    resp = await client.post(
        f"/api/v1/admin/promo-codes/{promo['id']}/toggle", headers=moderator
    )
    assert resp.json()["is_active"] is False


async def test_sms_fallback_on_accept(client, session_factory, monkeypatch):
    """Без зарегистрированных устройств критическое событие уходит в SMS."""
    from app.services import notifications

    sent: list[tuple[str, str]] = []

    async def fake_send_sms(phone: str, text: str) -> bool:
        sent.append((phone, text))
        return True

    monkeypatch.setattr(notifications, "send_sms", fake_send_sms)

    provider_headers, provider_id, service_id = await _active_provider(
        client, session_factory, "+77016660007"
    )
    customer = await login(client, "+77016660008")

    start = datetime.now(UTC) + timedelta(days=1)
    resp = await client.post(
        "/api/v1/orders",
        headers=customer,
        json={
            "service_id": service_id,
            "provider_user_id": provider_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=2)).isoformat(),
            "price_unit": "hour",
        },
    )
    order_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/orders/{order_id}/accept", headers=provider_headers)
    assert resp.status_code == 200, resp.text

    assert len(sent) == 1
    phone, text = sent[0]
    assert phone == "+77016660008"
    assert "принят" in text.lower()
