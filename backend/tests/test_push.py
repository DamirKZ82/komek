"""Тесты регистрации устройств и отправки пушей."""

from __future__ import annotations

import sqlalchemy as sa

from app.models.user import Device
from app.services import notifications
from tests.conftest import login


async def test_register_device_and_takeover(client, session_factory):
    headers_a = await login(client, "+77013330001")
    resp = await client.post(
        "/api/v1/me/devices",
        headers=headers_a,
        json={"platform": "android", "push_token": "ExponentPushToken[test-token-1]"},
    )
    assert resp.status_code == 200, resp.text

    # Тот же токен от другого аккаунта — токен «переезжает» (один телефон, новый вход).
    headers_b = await login(client, "+77013330002")
    resp = await client.post(
        "/api/v1/me/devices",
        headers=headers_b,
        json={"platform": "android", "push_token": "ExponentPushToken[test-token-1]"},
    )
    assert resp.status_code == 200

    async with session_factory() as session:
        devices = (
            await session.scalars(
                sa.select(Device).where(
                    Device.push_token == "ExponentPushToken[test-token-1]"
                )
            )
        ).all()
        assert len(devices) == 1


async def test_push_sent_on_order_response(client, session_factory, monkeypatch):
    """Отклик на заявку триггерит пуш заказчику через Expo API."""
    from datetime import UTC, datetime, timedelta

    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    sent_batches: list[list[dict]] = []

    async def fake_send(messages):
        sent_batches.append(messages)

    monkeypatch.setattr(notifications, "_send_expo_batch", fake_send)

    # Заказчик с устройством.
    customer_headers = await login(client, "+77013330003")
    await client.post(
        "/api/v1/me/devices",
        headers=customer_headers,
        json={"platform": "ios", "push_token": "ExponentPushToken[customer-dev]"},
    )

    # Активный исполнитель.
    provider_headers = await login(client, "+77013330004")
    await client.post("/api/v1/providers/me", headers=provider_headers)
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()

    categories = (await client.get("/api/v1/catalog/categories")).json()
    babysitter = next(
        s for c in categories for s in c["services"] if s["code"] == "babysitter_hourly"
    )
    start = datetime.now(UTC) + timedelta(days=1)
    resp = await client.post(
        "/api/v1/orders",
        headers=customer_headers,
        json={
            "service_id": babysitter["id"],
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=2)).isoformat(),
            "price_unit": "hour",
            "unit_price": "2000",
        },
    )
    order_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/orders/{order_id}/responses", headers=provider_headers, json={}
    )
    assert resp.status_code == 201, resp.text

    assert len(sent_batches) == 1
    message = sent_batches[0][0]
    assert message["to"] == "ExponentPushToken[customer-dev]"
    assert "отклик" in message["title"].lower() or "отклик" in message["body"].lower()
