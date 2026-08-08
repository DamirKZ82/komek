"""Тесты чата (маскировка контактов) и модерации (верификация, жалобы)."""

from __future__ import annotations

import sqlalchemy as sa

from app.models.enums import StaffRole
from app.models.user import User
from app.services.chat import mask_contacts
from tests.conftest import login


def test_mask_contacts_patterns():
    masked, was_masked = mask_contacts("Позвоните мне +7 701 123 45 67 или на почту a@b.kz")
    assert was_masked
    assert "+7 701" not in masked
    assert "a@b.kz" not in masked

    masked, was_masked = mask_contacts("пишите в whatsapp: 87071234567")
    assert was_masked
    assert "87071234567" not in masked

    masked, was_masked = mask_contacts("мой ник @nurse_aliya, https://t.me/nurse_aliya")
    assert was_masked
    assert "@nurse_aliya" not in masked
    assert "t.me" not in masked

    # Обычный текст не трогаем.
    masked, was_masked = mask_contacts("Приду завтра к 10:00, возьму документы")
    assert not was_masked


async def _make_staff(session_factory, phone: str) -> None:
    async with session_factory() as session:
        await session.execute(
            sa.update(User).where(User.phone == phone).values(staff_role=StaffRole.MODERATOR)
        )
        await session.commit()


async def test_verification_flow(client, session_factory):
    """Исполнитель подаёт заявку → модератор одобряет → анкета активна и в поиске."""
    provider_headers = await login(client, "+77011110001")
    resp = await client.post("/api/v1/providers/me", headers=provider_headers)
    assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/providers/me/verification",
        headers=provider_headers,
        json={"target_level": "level_2"},
    )
    assert resp.status_code == 201, resp.text
    request_id = resp.json()["id"]
    assert resp.json()["status"] == "submitted"

    # Повторная подача — конфликт.
    resp = await client.post("/api/v1/providers/me/verification", headers=provider_headers)
    assert resp.status_code == 409

    # Не-модератору очередь недоступна.
    resp = await client.get("/api/v1/admin/verification-requests", headers=provider_headers)
    assert resp.status_code == 403

    moderator_headers = await login(client, "+77011110002")
    await _make_staff(session_factory, "+77011110002")

    resp = await client.get("/api/v1/admin/verification-requests", headers=moderator_headers)
    assert resp.status_code == 200
    assert any(r["id"] == request_id for r in resp.json()["items"])

    resp = await client.post(
        f"/api/v1/admin/verification-requests/{request_id}/decision",
        headers=moderator_headers,
        json={"approve": True, "checklist": {"documents_match": True, "interview_passed": True}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    # Профиль стал активным и видим.
    resp = await client.get("/api/v1/providers/me", headers=provider_headers)
    assert resp.json()["status"] == "active"
    assert resp.json()["verification_level"] == "level_2"


async def test_chat_masks_contacts_until_paid(client, session_factory):
    provider_headers = await login(client, "+77011110003")
    await client.post("/api/v1/providers/me", headers=provider_headers)
    provider_id = (await client.get("/api/v1/me", headers=provider_headers)).json()["id"]

    customer_headers = await login(client, "+77011110004")
    resp = await client.post(
        "/api/v1/chats", headers=customer_headers, json={"peer_user_id": provider_id}
    )
    assert resp.status_code == 201, resp.text
    thread = resp.json()
    assert thread["contacts_unlocked"] is False

    resp = await client.post(
        f"/api/v1/chats/{thread['id']}/messages",
        headers=customer_headers,
        json={"body": "Здравствуйте! Мой номер +77011234567, наберите в whatsapp"},
    )
    assert resp.status_code == 201, resp.text
    message = resp.json()
    assert message["contacts_masked"] is True
    assert "+77011234567" not in message["body"]

    # Вторая сторона видит замаскированный текст.
    resp = await client.get(
        f"/api/v1/chats/{thread['id']}/messages", headers=provider_headers
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert "+77011234567" not in (items[0]["body"] or "")

    # Список диалогов у исполнителя: непрочитанных ноль после чтения.
    resp = await client.get("/api/v1/chats", headers=provider_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["unread_count"] == 0


async def test_safety_complaint_suspends_provider(client, session_factory):
    """Жалоба категории safety автоматически приостанавливает активного исполнителя."""
    import uuid as uuid_module

    from app.models.enums import ProviderStatus
    from app.models.provider import ProviderProfile

    provider_headers = await login(client, "+77011110005")
    await client.post("/api/v1/providers/me", headers=provider_headers)
    provider_id = (await client.get("/api/v1/me", headers=provider_headers)).json()["id"]
    provider_uuid = uuid_module.UUID(provider_id)

    async with session_factory() as session:
        await session.execute(
            sa.update(ProviderProfile)
            .where(ProviderProfile.user_id == provider_uuid)
            .values(status=ProviderStatus.ACTIVE)
        )
        await session.commit()

    customer_headers = await login(client, "+77011110006")
    resp = await client.post(
        "/api/v1/complaints",
        headers=customer_headers,
        json={
            "target_user_id": provider_id,
            "category": "safety",
            "description": "Исполнитель вёл себя агрессивно при визите",
        },
    )
    assert resp.status_code == 201, resp.text
    complaint = resp.json()
    assert complaint["auto_suspended"] is True

    async with session_factory() as session:
        profile = await session.get(ProviderProfile, provider_uuid)
        assert profile.status == ProviderStatus.SUSPENDED

    # Модератор отклоняет жалобу — профиль возвращается в поиск.
    moderator_headers = await login(client, "+77011110007")
    await _make_staff(session_factory, "+77011110007")
    resp = await client.post(
        f"/api/v1/admin/complaints/{complaint['id']}/resolve",
        headers=moderator_headers,
        json={"resolution": "Жалоба не подтвердилась", "dismiss": True},
    )
    assert resp.status_code == 200, resp.text

    async with session_factory() as session:
        profile = await session.get(ProviderProfile, provider_uuid)
        assert profile.status == ProviderStatus.ACTIVE
