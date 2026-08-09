"""Тесты платёжного контура: холд, списание, возвраты, вебхуки, сверка."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid as uuid_module
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa

from tests.conftest import login
from tests.test_chat_moderation import _make_staff


async def _order_until_confirmed(
    client, session_factory, provider_phone: str, customer_phone: str, hours_ahead: int = 48
):
    """Заказ типа B, доведённый до статуса confirmed (то есть с холдом)."""
    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    provider = await login(client, provider_phone)
    await client.post("/api/v1/providers/me", headers=provider)
    provider_id = (await client.get("/api/v1/me", headers=provider)).json()["id"]
    categories = (await client.get("/api/v1/catalog/categories")).json()
    service = next(
        s for c in categories for s in c["services"] if s["code"] == "babysitter_hourly"
    )
    await client.put(
        "/api/v1/providers/me/services",
        headers=provider,
        json=[{"service_id": service["id"], "price": "2000", "price_unit": "hour"}],
    )
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()

    customer = await login(client, customer_phone)
    start = datetime.now(UTC) + timedelta(hours=hours_ahead)
    resp = await client.post(
        "/api/v1/orders",
        headers=customer,
        json={
            "service_id": service["id"],
            "provider_user_id": provider_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=2)).isoformat(),
            "price_unit": "hour",
        },
    )
    order = resp.json()
    await client.post(f"/api/v1/orders/{order['id']}/accept", headers=provider)
    resp = await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=customer)
    assert resp.status_code == 200, resp.text
    return customer, provider, resp.json()


async def _payment_for(session_factory, order_id: str):
    from app.models.payment import Payment

    async with session_factory() as session:
        return await session.scalar(
            sa.select(Payment).where(Payment.order_id == uuid_module.UUID(order_id))
        )


async def test_hold_created_with_psp_reference(client, session_factory):
    """Подтверждение заказа холдирует деньги через шлюз и сохраняет ссылку эквайера."""
    from app.models.enums import PaymentStatus

    _, _, order = await _order_until_confirmed(
        client, session_factory, "+77018880001", "+77018880002"
    )
    payment = await _payment_for(session_factory, order["id"])
    assert payment is not None
    assert payment.status == PaymentStatus.HELD
    assert payment.psp_reference is not None and payment.psp_reference.startswith("sbx_")
    assert payment.card_mask is not None
    assert payment.idempotency_key == f"hold-{order['id']}"


async def test_capture_and_overhold_refund(client, session_factory):
    """Списывается фактическая сумма; излишек холда возвращается заказчику."""
    from app.models.enums import PaymentStatus

    customer, provider, order = await _order_until_confirmed(
        client, session_factory, "+77018880003", "+77018880004"
    )
    await client.post(f"/api/v1/orders/{order['id']}/check-in", headers=provider, json={})
    await client.post(f"/api/v1/orders/{order['id']}/check-out", headers=provider, json={})

    resp = await client.post(f"/api/v1/orders/{order['id']}/pay", headers=customer)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"

    payment = await _payment_for(session_factory, order["id"])
    assert payment.status == PaymentStatus.CAPTURED
    assert payment.captured_amount == Decimal("4000.00")
    # Холд был на ту же сумму — возвращать нечего.
    assert payment.refunded_amount == Decimal("0")


async def test_cancel_refunds_hold_minus_penalty(client, session_factory):
    """Отмена заказчиком за 6 часов: штраф 20% удержан, остальное возвращено."""
    from app.models.enums import PaymentStatus

    customer, _, order = await _order_until_confirmed(
        client, session_factory, "+77018880005", "+77018880006", hours_ahead=6
    )
    assert Decimal(order["estimated_total"]) == Decimal("4000.00")

    resp = await client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        headers=customer,
        json={"reason": "изменились планы"},
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["cancellation_penalty"]) == Decimal("800.00")

    payment = await _payment_for(session_factory, order["id"])
    assert payment.status == PaymentStatus.PARTIALLY_REFUNDED
    assert payment.refunded_amount == Decimal("3200.00")  # 4000 − 800
    assert payment.captured_amount == Decimal("800.00")


async def test_cancel_by_provider_refunds_everything(client, session_factory):
    """Отмена исполнителем: заказчику возвращается вся сумма, штрафа нет."""
    from app.models.enums import PaymentStatus

    _, provider, order = await _order_until_confirmed(
        client, session_factory, "+77018880007", "+77018880008", hours_ahead=6
    )
    resp = await client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        headers=provider,
        json={"reason": "заболела"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cancellation_penalty"] is None

    payment = await _payment_for(session_factory, order["id"])
    assert payment.status == PaymentStatus.REFUNDED
    assert payment.refunded_amount == Decimal("4000.00")


# --- Вебхуки ------------------------------------------------------------------


def _signed(body: dict, secret: str) -> tuple[str, dict[str, str]]:
    raw = json.dumps(body)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw.encode(), hashlib.sha256
    ).hexdigest()
    return raw, {"X-Signature": signature, "X-Timestamp": timestamp}


async def test_webhook_captures_order(client, session_factory, monkeypatch):
    """Вебхук payment.captured переводит завершённый заказ в «оплачен»."""
    from app.core.config import settings
    from app.models.enums import PaymentStatus

    monkeypatch.setattr(settings, "payment_webhook_secret", "whsec_test")

    customer, provider, order = await _order_until_confirmed(
        client, session_factory, "+77018880009", "+77018880010"
    )
    await client.post(f"/api/v1/orders/{order['id']}/check-in", headers=provider, json={})
    await client.post(f"/api/v1/orders/{order['id']}/check-out", headers=provider, json={})

    payment = await _payment_for(session_factory, order["id"])
    body = {
        "event_id": "evt_1",
        "type": "payment.captured",
        "data": {"id": payment.psp_reference},
    }
    raw, headers = _signed(body, "whsec_test")

    resp = await client.post("/api/v1/webhooks/payments", content=raw, headers=headers)
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"/api/v1/orders/{order['id']}", headers=customer)
    assert resp.json()["status"] == "paid"

    payment = await _payment_for(session_factory, order["id"])
    assert payment.status == PaymentStatus.CAPTURED

    # Повтор того же события ничего не ломает (идемпотентность).
    resp = await client.post("/api/v1/webhooks/payments", content=raw, headers=headers)
    assert resp.status_code == 200


async def test_webhook_rejects_bad_signature(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "payment_webhook_secret", "whsec_test")

    body = {"event_id": "evt_2", "type": "payment.captured", "data": {"id": "sbx_x"}}
    raw = json.dumps(body)
    timestamp = str(int(datetime.now(UTC).timestamp()))

    resp = await client.post(
        "/api/v1/webhooks/payments",
        content=raw,
        headers={"X-Signature": "deadbeef", "X-Timestamp": timestamp},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "webhook_bad_signature"

    # Без подписи вовсе — тоже отказ.
    resp = await client.post("/api/v1/webhooks/payments", content=raw)
    assert resp.status_code == 403


async def test_webhook_rejects_replay(client, monkeypatch):
    """Старое событие отбрасывается — защита от повторной отправки перехваченного запроса."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "payment_webhook_secret", "whsec_test")

    body = {"event_id": "evt_3", "type": "payment.captured", "data": {"id": "sbx_x"}}
    raw = json.dumps(body)
    old = str(int((datetime.now(UTC) - timedelta(hours=1)).timestamp()))
    signature = hmac.new(
        b"whsec_test", old.encode() + b"." + raw.encode(), hashlib.sha256
    ).hexdigest()

    resp = await client.post(
        "/api/v1/webhooks/payments",
        content=raw,
        headers={"X-Signature": signature, "X-Timestamp": old},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "webhook_expired"


async def test_reconciliation_finds_stale_hold(client, session_factory):
    """Сверка показывает зависший холд по отменённому заказу."""
    from app.models.enums import OrderStatus, PaymentStatus
    from app.models.order import Order
    from app.models.payment import Payment

    _, _, order = await _order_until_confirmed(
        client, session_factory, "+77018880011", "+77018880012"
    )
    # Имитируем сбой: заказ отменён, а холд остался.
    async with session_factory() as session:
        await session.execute(
            sa.update(Order)
            .where(Order.id == uuid_module.UUID(order["id"]))
            .values(status=OrderStatus.CANCELLED)
        )
        await session.execute(
            sa.update(Payment)
            .where(Payment.order_id == uuid_module.UUID(order["id"]))
            .values(status=PaymentStatus.HELD)
        )
        await session.commit()

    moderator = await login(client, "+77018880013")
    await _make_staff(session_factory, "+77018880013")

    resp = await client.get("/api/v1/admin/reconciliation", headers=moderator)
    assert resp.status_code == 200, resp.text
    stale = resp.json()["stale_holds"]
    assert any(item["order"] == order["code"] for item in stale)
