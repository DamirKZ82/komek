"""Смоук-тесты ключевых сценариев MVP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.conftest import login


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_catalog_localized(client):
    resp = await client.get("/api/v1/catalog/categories", params={"locale": "kk"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    children = next(c for c in data if c["code"] == "children")
    assert children["name"] == "Балалар"
    # В MVP активны только 2 услуги вертикали «Дети».
    assert {s["code"] for s in children["services"]} == {"babysitter_hourly", "nanny_fulltime"}


async def test_otp_login_and_me(client):
    headers = await login(client, "+77011234567")
    resp = await client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["phone"] == "+77011234567"


async def test_invalid_phone_rejected(client):
    resp = await client.post("/api/v1/auth/otp/request", json={"phone": "12345"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_phone"


async def _make_active_provider(client, phone: str) -> tuple[dict, str]:
    """Регистрирует исполнителя с услугой «бебиситтер» и активирует анкету напрямую."""
    headers = await login(client, phone)
    resp = await client.post("/api/v1/providers/me", headers=headers)
    assert resp.status_code == 201, resp.text
    user_id = (await client.get("/api/v1/me", headers=headers)).json()["id"]

    categories = (await client.get("/api/v1/catalog/categories")).json()
    babysitter = next(
        s
        for c in categories
        for s in c["services"]
        if s["code"] == "babysitter_hourly"
    )
    resp = await client.put(
        "/api/v1/providers/me/services",
        headers=headers,
        json=[{"service_id": babysitter["id"], "price": "2500", "price_unit": "hour"}],
    )
    assert resp.status_code == 200, resp.text
    return headers, user_id


async def test_full_order_lifecycle(client, session_factory):
    """Каталожный сценарий: заказ конкретному исполнителю до завершения."""
    import sqlalchemy as sa

    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    provider_headers, provider_id = await _make_active_provider(client, "+77020000001")

    # Активируем анкету напрямую в БД (модерация — отдельный поток).
    async with session_factory() as session:
        await session.execute(
            sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE)
        )
        await session.commit()

    customer_headers = await login(client, "+77051230002")
    categories = (await client.get("/api/v1/catalog/categories")).json()
    babysitter = next(
        s for c in categories for s in c["services"] if s["code"] == "babysitter_hourly"
    )

    start = datetime.now(UTC) + timedelta(days=2)
    resp = await client.post(
        "/api/v1/orders",
        headers=customer_headers,
        json={
            "service_id": babysitter["id"],
            "provider_user_id": provider_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=3)).isoformat(),
            "price_unit": "hour",
            "comment": "Двое детей, 3 и 5 лет",
        },
    )
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["status"] == "sent"
    assert order["estimated_total"] == "7500.00"
    assert order["is_urgent"] is False

    order_id = order["id"]
    resp = await client.post(f"/api/v1/orders/{order_id}/accept", headers=provider_headers)
    assert resp.status_code == 200 and resp.json()["status"] == "accepted"

    resp = await client.post(f"/api/v1/orders/{order_id}/confirm", headers=customer_headers)
    assert resp.status_code == 200 and resp.json()["status"] == "confirmed"

    resp = await client.post(
        f"/api/v1/orders/{order_id}/check-in", headers=provider_headers, json={}
    )
    assert resp.status_code == 200 and resp.json()["status"] == "in_progress"

    resp = await client.post(
        f"/api/v1/orders/{order_id}/check-out", headers=provider_headers, json={}
    )
    body = resp.json()
    assert resp.status_code == 200 and body["status"] == "completed"
    assert body["final_total"] is not None
    # Тип B: комиссия 15% с суммы заказа (п. 5.8 ТЗ).
    assert body["commission_rate"] == "0.1500"

    # Оплата заказчиком (эквайринг пока имитируется).
    resp = await client.post(f"/api/v1/orders/{order_id}/pay", headers=customer_headers)
    body = resp.json()
    assert resp.status_code == 200 and body["status"] == "paid"
    assert body["commission_amount"] is not None
    assert body["provider_payout_amount"] is not None

    # Проверка стейт-машины: завершённый заказ нельзя отменить.
    resp = await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        headers=customer_headers,
        json={"reason": "передумал"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_status_transition"

    # Оплаченный заказ открывает отзыв; оценка 5 публикуется сразу.
    resp = await client.post(
        f"/api/v1/orders/{order_id}/reviews",
        headers=customer_headers,
        json={"rating": 5, "rating_punctuality": 5, "text": "Отличная няня!"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "published"

    # Рейтинг исполнителя пересчитался.
    resp = await client.get(f"/api/v1/providers/{provider_id}", headers=customer_headers)
    assert resp.json()["rating_avg"] == "5.00"
    assert resp.json()["rating_count"] == 1


async def test_request_flow_with_responses(client, session_factory):
    """Биржевой сценарий: заявка → отклик → выбор исполнителя."""
    import sqlalchemy as sa

    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    provider_headers, provider_id = await _make_active_provider(client, "+77471234567")
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()

    customer_headers = await login(client, "+77050000004")
    categories = (await client.get("/api/v1/catalog/categories")).json()
    babysitter = next(
        s for c in categories for s in c["services"] if s["code"] == "babysitter_hourly"
    )

    start = datetime.now(UTC) + timedelta(hours=6)  # < 12 часов — срочный заказ
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
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["status"] == "published"
    assert order["is_urgent"] is True

    # Заявка видна в ленте исполнителя.
    resp = await client.get("/api/v1/orders/feed", headers=provider_headers)
    assert resp.status_code == 200
    assert any(o["id"] == order["id"] for o in resp.json()["items"])

    resp = await client.post(
        f"/api/v1/orders/{order['id']}/responses",
        headers=provider_headers,
        json={"offered_price": "2200", "message": "Готова приехать"},
    )
    assert resp.status_code == 201, resp.text
    response_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/orders/{order['id']}/responses/{response_id}/accept",
        headers=customer_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["provider_user_id"] == provider_id
    assert body["unit_price"] == "2200.00"


async def test_provider_search(client, session_factory):
    import sqlalchemy as sa

    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    _, provider_id = await _make_active_provider(client, "+77060000005")
    async with session_factory() as session:
        await session.execute(sa.update(ProviderProfile).values(status=ProviderStatus.ACTIVE))
        await session.commit()

    customer_headers = await login(client, "+77070000006")
    resp = await client.get("/api/v1/providers/search", headers=customer_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(card["user_id"] == provider_id for card in items)
    card = next(c for c in items if c["user_id"] == provider_id)
    assert card["min_price"] == "2500.00"
