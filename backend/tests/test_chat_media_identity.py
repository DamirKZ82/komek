"""Тесты вложений в чате и подтверждения личности."""

from __future__ import annotations

from tests.conftest import login

JPEG_STUB = b"\xff\xd8\xff\xe0" + b"0" * 128
AUDIO_STUB = b"\x00\x00\x00\x20ftypM4A " + b"0" * 128


def _local_media(monkeypatch, tmp_path):
    from app.services import storage as storage_module

    monkeypatch.setattr(
        storage_module, "_media_storage", storage_module.LocalStorage(tmp_path)
    )


async def _open_thread(client, provider_phone: str, customer_phone: str):
    provider_headers = await login(client, provider_phone)
    await client.post("/api/v1/providers/me", headers=provider_headers)
    provider_id = (await client.get("/api/v1/me", headers=provider_headers)).json()["id"]

    customer_headers = await login(client, customer_phone)
    resp = await client.post(
        "/api/v1/chats", headers=customer_headers, json={"peer_user_id": provider_id}
    )
    assert resp.status_code == 201, resp.text
    return customer_headers, provider_headers, resp.json()


async def test_chat_photo_and_voice(client, tmp_path, monkeypatch):
    _local_media(monkeypatch, tmp_path)
    customer, provider, thread = await _open_thread(client, "+77017770001", "+77017770002")

    # Фото с подписью: контакты в подписи маскируются, как и в тексте.
    resp = await client.post(
        f"/api/v1/chats/{thread['id']}/attachments",
        headers=customer,
        files={"file": ("photo.jpg", JPEG_STUB, "image/jpeg")},
        data={"caption": "Вот подъезд, звоните +77011234567"},
    )
    assert resp.status_code == 201, resp.text
    photo = resp.json()
    assert photo["message_type"] == "image"
    assert photo["has_attachment"] is True
    assert "+77011234567" not in photo["body"]
    assert photo["contacts_masked"] is True

    # Голосовое с длительностью.
    resp = await client.post(
        f"/api/v1/chats/{thread['id']}/attachments",
        headers=customer,
        files={"file": ("voice.m4a", AUDIO_STUB, "audio/m4a")},
        data={"duration_seconds": "7"},
    )
    assert resp.status_code == 201, resp.text
    voice = resp.json()
    assert voice["message_type"] == "audio"
    assert voice["duration_seconds"] == 7

    # Недопустимый тип файла.
    resp = await client.post(
        f"/api/v1/chats/{thread['id']}/attachments",
        headers=customer,
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unsupported_file_type"

    # Собеседник скачивает вложение.
    resp = await client.get(
        f"/api/v1/chats/{thread['id']}/attachments/{photo['id']}", headers=provider
    )
    assert resp.status_code == 200
    assert resp.content == JPEG_STUB

    # Посторонний не имеет доступа ни к диалогу, ни к файлу.
    outsider = await login(client, "+77017770003")
    resp = await client.get(
        f"/api/v1/chats/{thread['id']}/attachments/{photo['id']}", headers=outsider
    )
    assert resp.status_code == 404

    # Ключ хранилища наружу не отдаётся.
    resp = await client.get(f"/api/v1/chats/{thread['id']}/messages", headers=customer)
    assert all("attachment_key" not in item for item in resp.json()["items"])


async def test_customer_identity_verification(client):
    """Заглушка KYC подтверждает личность и выдаёт значок «проверенный»."""
    customer = await login(client, "+77017770004")

    resp = await client.get("/api/v1/me", headers=customer)
    assert resp.json()["identity_verified_at"] is None

    resp = await client.post(
        "/api/v1/me/identity", headers=customer, json={"session_token": "stub:900101300123"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["identity_verified_at"] is not None

    # Повторное подтверждение — конфликт.
    resp = await client.post(
        "/api/v1/me/identity", headers=customer, json={"session_token": "stub:900101300123"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already_verified"


async def test_identity_badge_visible_to_provider(client):
    """Исполнитель видит в диалоге, что заказчик прошёл проверку (п. 4.3 ТЗ)."""
    customer, provider, thread = await _open_thread(client, "+77017770005", "+77017770006")

    resp = await client.get("/api/v1/chats", headers=provider)
    assert resp.json()[0]["peer"]["identity_verified"] is False

    await client.post(
        "/api/v1/me/identity", headers=customer, json={"session_token": "stub:900101300123"}
    )

    resp = await client.get("/api/v1/chats", headers=provider)
    assert resp.json()[0]["peer"]["identity_verified"] is True


async def test_provider_identity_grants_level_1(client):
    """Для исполнителя подтверждение личности — это уровень 1 (п. 4.1 ТЗ)."""
    provider = await login(client, "+77017770007")
    await client.post("/api/v1/providers/me", headers=provider)

    resp = await client.get("/api/v1/providers/me", headers=provider)
    assert resp.json()["verification_level"] == "level_0"

    resp = await client.post(
        "/api/v1/me/identity", headers=provider, json={"session_token": "stub:900101300123"}
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/providers/me", headers=provider)
    assert resp.json()["verification_level"] == "level_1"
