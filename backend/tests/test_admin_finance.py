"""Тесты: штрафы за отмену, реестр выплат, модерация отзывов, статистика."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa

from tests.conftest import login
from tests.test_chat_moderation import _make_staff


async def _paid_order(client, session_factory, provider_phone: str, customer_phone: str):
    """Прогоняет заказ типа B до PAID; возвращает (customer_headers, provider_headers, order)."""
    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    provider_headers = await login(client, provider_phone)
    await client.post("/api/v1/providers/me", headers=provider_headers)
    provider_id = (await client.get("/api/v1/me", headers=provider_headers)).json()["id"]
    categories = (await client.get("/api/v1/catalog/categories")).json()
    babysitter = next(
        s for c in categories for s in c["services"] if s["code"] == "babysitter_hourly"
    )
    await client.put(
        "/api/v1/providers/me/services",
        headers=provider_headers,
        json=[{"service_id": babysitter["id"], "price": "2000", "price_unit": "hour"}],
    )
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()

    customer_headers = await login(client, customer_phone)
    start = datetime.now(UTC) + timedelta(days=1)
    resp = await client.post(
        "/api/v1/orders",
        headers=customer_headers,
        json={
            "service_id": babysitter["id"],
            "provider_user_id": provider_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=2)).isoformat(),
            "price_unit": "hour",
        },
    )
    order = resp.json()
    await client.post(f"/api/v1/orders/{order['id']}/accept", headers=provider_headers)
    await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=customer_headers)
    await client.post(f"/api/v1/orders/{order['id']}/check-in", headers=provider_headers, json={})
    await client.post(f"/api/v1/orders/{order['id']}/check-out", headers=provider_headers, json={})
    resp = await client.post(f"/api/v1/orders/{order['id']}/pay", headers=customer_headers)
    assert resp.json()["status"] == "paid"
    return customer_headers, provider_headers, resp.json()


async def test_cancellation_penalty(client, session_factory):
    """Отмена подтверждённого заказа за ~6 часов до начала → штраф 20%."""
    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    provider_headers = await login(client, "+77015550001")
    await client.post("/api/v1/providers/me", headers=provider_headers)
    provider_id = (await client.get("/api/v1/me", headers=provider_headers)).json()["id"]
    categories = (await client.get("/api/v1/catalog/categories")).json()
    babysitter = next(
        s for c in categories for s in c["services"] if s["code"] == "babysitter_hourly"
    )
    await client.put(
        "/api/v1/providers/me/services",
        headers=provider_headers,
        json=[{"service_id": babysitter["id"], "price": "2000", "price_unit": "hour"}],
    )
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()

    customer_headers = await login(client, "+77015550002")
    start = datetime.now(UTC) + timedelta(hours=6)  # попадаем в правило «< 24ч → 20%»
    resp = await client.post(
        "/api/v1/orders",
        headers=customer_headers,
        json={
            "service_id": babysitter["id"],
            "provider_user_id": provider_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=3)).isoformat(),
            "price_unit": "hour",
        },
    )
    order = resp.json()
    assert Decimal(order["estimated_total"]) == Decimal("6000.00")

    await client.post(f"/api/v1/orders/{order['id']}/accept", headers=provider_headers)
    await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=customer_headers)

    resp = await client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        headers=customer_headers,
        json={"reason": "планы изменились"},
    )
    body = resp.json()
    assert body["status"] == "cancelled"
    assert Decimal(body["cancellation_penalty"]) == Decimal("1200.00")  # 20% от 6000


async def test_payout_registry(client, session_factory):
    _, _, order = await _paid_order(client, session_factory, "+77015550003", "+77015550004")

    moderator = await login(client, "+77015550005")
    await _make_staff(session_factory, "+77015550005")

    # Формируем реестр: комиссия 15% удержана, исполнителю — 85%.
    resp = await client.post("/api/v1/admin/payouts/build", headers=moderator)
    assert resp.status_code == 200, resp.text
    payouts = resp.json()
    assert len(payouts) == 1
    payout = payouts[0]
    expected = (Decimal(order["final_total"]) * Decimal("0.85")).quantize(Decimal("0.01"))
    assert Decimal(payout["amount"]) == expected
    assert payout["status"] == "scheduled"
    assert len(payout["items"]) == 1

    # Повторный build не дублирует заказы.
    resp = await client.post("/api/v1/admin/payouts/build", headers=moderator)
    assert resp.json() == []

    # Отметка «выплачено».
    resp = await client.post(
        f"/api/v1/admin/payouts/{payout['id']}/mark-paid", headers=moderator
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"


async def test_low_rating_review_moderation(client, session_factory):
    customer_headers, _, order = await _paid_order(
        client, session_factory, "+77015550006", "+77015550007"
    )

    # Оценка 2 уходит в модерацию.
    resp = await client.post(
        f"/api/v1/orders/{order['id']}/reviews",
        headers=customer_headers,
        json={"rating": 2, "text": "Опоздала на час"},
    )
    assert resp.status_code == 201
    review = resp.json()
    assert review["status"] == "pending"

    moderator = await login(client, "+77015550008")
    await _make_staff(session_factory, "+77015550008")

    resp = await client.get("/api/v1/admin/reviews", headers=moderator)
    assert any(r["id"] == review["id"] for r in resp.json()["items"])

    resp = await client.post(
        f"/api/v1/admin/reviews/{review['id']}/decision",
        headers=moderator,
        json={"publish": True},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"

    # Рейтинг исполнителя пересчитан по опубликованному отзыву.
    resp = await client.get(
        f"/api/v1/providers/{order['provider_user_id']}", headers=customer_headers
    )
    assert resp.json()["rating_avg"] == "2.00"


async def test_stats_endpoint(client, session_factory):
    await _paid_order(client, session_factory, "+77015550009", "+77015550010")
    moderator = await login(client, "+77015550011")
    await _make_staff(session_factory, "+77015550011")

    resp = await client.get("/api/v1/admin/stats", headers=moderator)
    assert resp.status_code == 200, resp.text
    stats = resp.json()
    assert stats["orders_by_status"].get("paid", 0) >= 1
    assert Decimal(stats["gmv_paid"]) > 0
    assert Decimal(stats["commission_earned"]) > 0
    assert stats["users_total"] >= 2


async def test_provider_schedule(client):
    headers = await login(client, "+77015550012")
    await client.post("/api/v1/providers/me", headers=headers)

    resp = await client.put(
        "/api/v1/providers/me/schedule",
        headers=headers,
        json=[
            {"weekday": 0, "time_from": "09:00", "time_to": "18:00"},
            {"weekday": 2, "time_from": "09:00", "time_to": "18:00"},
        ],
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2

    # Некорректный интервал отклоняется.
    resp = await client.put(
        "/api/v1/providers/me/schedule",
        headers=headers,
        json=[{"weekday": 0, "time_from": "18:00", "time_to": "09:00"}],
    )
    assert resp.status_code == 409

    resp = await client.get("/api/v1/providers/me/schedule", headers=headers)
    assert len(resp.json()) == 2
