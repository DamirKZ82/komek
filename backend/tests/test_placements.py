"""Тесты гибридной монетизации: fee за подбор (тип A) и гарантия замены."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa

from tests.conftest import login


async def _make_active_nanny(client, session_factory, phone: str) -> tuple[dict, str, str]:
    """Активный исполнитель с услугой «няня постоянная» (тип A), помесячный тариф."""
    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    headers = await login(client, phone)
    await client.post("/api/v1/providers/me", headers=headers)
    user_id = (await client.get("/api/v1/me", headers=headers)).json()["id"]

    categories = (await client.get("/api/v1/catalog/categories")).json()
    nanny = next(
        s for c in categories for s in c["services"] if s["code"] == "nanny_fulltime"
    )
    await client.put(
        "/api/v1/providers/me/services",
        headers=headers,
        json=[{"service_id": nanny["id"], "price": "300000", "price_unit": "month"}],
    )
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()
    return headers, user_id, nanny["id"]


async def test_placement_fee_and_replacement_guarantee(client, session_factory):
    provider_headers, provider_id, service_id = await _make_active_nanny(
        client, session_factory, "+77014440001"
    )
    customer_headers = await login(client, "+77014440002")

    start = datetime.now(UTC) + timedelta(days=3)
    resp = await client.post(
        "/api/v1/orders",
        headers=customer_headers,
        json={
            "service_id": service_id,
            "provider_user_id": provider_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=9)).isoformat(),
            "price_unit": "month",
        },
    )
    assert resp.status_code == 201, resp.text
    order = resp.json()

    # Исполнитель принимает, заказчик подтверждает найм → создаётся подбор с fee.
    await client.post(f"/api/v1/orders/{order['id']}/accept", headers=provider_headers)
    resp = await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=customer_headers)
    assert resp.status_code == 200, resp.text
    # Тип A: пара вне комиссионной логики.
    assert Decimal(resp.json()["commission_rate"]) == Decimal("0")

    resp = await client.get("/api/v1/placements/my", headers=customer_headers)
    assert resp.status_code == 200
    placements = resp.json()
    assert len(placements) == 1
    placement = placements[0]
    # Fee = 40% месячной ставки 300 000 ₸.
    assert Decimal(placement["fee_amount"]) == Decimal("120000.00")
    assert placement["fee_status"] == "pending"

    # Гарантия до оплаты не действует.
    resp = await client.post(
        f"/api/v1/placements/{placement['id']}/replacement",
        headers=customer_headers,
        json={"reason": "не подошла по графику"},
    )
    assert resp.status_code == 403

    # Оплата fee включает гарантию замены.
    resp = await client.post(
        f"/api/v1/placements/{placement['id']}/pay", headers=customer_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["fee_status"] == "paid"
    assert resp.json()["guarantee_until"] is not None

    # Запрос замены в течение гарантии.
    resp = await client.post(
        f"/api/v1/placements/{placement['id']}/replacement",
        headers=customer_headers,
        json={"reason": "не подошла по графику"},
    )
    assert resp.status_code == 200, resp.text

    # Повторный подбор: новый заказ у той же/другой няни → fee не взимается (waived).
    resp = await client.post(
        "/api/v1/orders",
        headers=customer_headers,
        json={
            "service_id": service_id,
            "provider_user_id": provider_id,
            "scheduled_start": (start + timedelta(days=7)).isoformat(),
            "scheduled_end": (start + timedelta(days=7, hours=9)).isoformat(),
            "price_unit": "month",
        },
    )
    order2 = resp.json()
    await client.post(f"/api/v1/orders/{order2['id']}/accept", headers=provider_headers)
    resp = await client.post(f"/api/v1/orders/{order2['id']}/confirm", headers=customer_headers)
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/placements/my", headers=customer_headers)
    placements = resp.json()
    assert len(placements) == 2
    newest = next(p for p in placements if p["order_id"] == order2["id"])
    assert newest["fee_status"] == "waived"
    assert Decimal(newest["fee_amount"]) == Decimal("0")
    assert newest["replacement_of_id"] == placement["id"]


async def test_commission_order_creates_hold(client, session_factory):
    """Тип B: подтверждение создаёт холд, чек-аут не закрывает заказ до оплаты."""
    from app.models.enums import PaymentStatus, ProviderStatus
    from app.models.payment import Payment
    from app.models.provider import ProviderProfile

    provider_headers = await login(client, "+77014440003")
    await client.post("/api/v1/providers/me", headers=provider_headers)
    provider_id = (await client.get("/api/v1/me", headers=provider_headers)).json()["id"]
    categories = (await client.get("/api/v1/catalog/categories")).json()
    babysitter = next(
        s for c in categories for s in c["services"] if s["code"] == "babysitter_hourly"
    )
    await client.put(
        "/api/v1/providers/me/services",
        headers=provider_headers,
        json=[{"service_id": babysitter["id"], "price": "2500", "price_unit": "hour"}],
    )
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()

    customer_headers = await login(client, "+77014440004")
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
    order_id = resp.json()["id"]
    await client.post(f"/api/v1/orders/{order_id}/accept", headers=provider_headers)
    await client.post(f"/api/v1/orders/{order_id}/confirm", headers=customer_headers)

    import uuid as uuid_module

    async with session_factory() as session:
        hold = await session.scalar(
            sa.select(Payment).where(Payment.order_id == uuid_module.UUID(order_id))
        )
        assert hold is not None
        assert hold.status == PaymentStatus.HELD

    # До оплаты отзыв недоступен (заказ ещё не PAID).
    await client.post(f"/api/v1/orders/{order_id}/check-in", headers=provider_headers, json={})
    await client.post(f"/api/v1/orders/{order_id}/check-out", headers=provider_headers, json={})
    resp = await client.post(
        f"/api/v1/orders/{order_id}/reviews", headers=customer_headers, json={"rating": 5}
    )
    assert resp.status_code == 409

    # После оплаты холд стал списанием.
    await client.post(f"/api/v1/orders/{order_id}/pay", headers=customer_headers)
    async with session_factory() as session:
        payment = await session.scalar(
            sa.select(Payment).where(Payment.order_id == uuid_module.UUID(order_id))
        )
        assert payment.status == PaymentStatus.CAPTURED
