"""Тесты флоу документов по ТЗ 4.2: согласие, PDF-only, связка ИИН, протухание."""

from __future__ import annotations

import uuid as uuid_module
from datetime import date, timedelta

import sqlalchemy as sa

from app.models.verification import DocumentAccessLog
from tests.conftest import login
from tests.test_chat_moderation import _make_staff

PDF_STUB = b"%PDF-1.4\n" + b"0" * 64
PNG_STUB = b"\x89PNG\r\n\x1a\n" + b"0" * 64


async def _grant_consent(client, headers) -> None:
    resp = await client.post(
        "/api/v1/me/consents",
        headers=headers,
        json={"consent_type": "background_check", "document_version": "1.0"},
    )
    assert resp.status_code == 200, resp.text


def _local_storage(monkeypatch, tmp_path):
    from app.services import storage as storage_module

    monkeypatch.setattr(storage_module, "_storage", storage_module.LocalStorage(tmp_path))


async def test_upload_requires_consent_and_pdf(client, session_factory, tmp_path, monkeypatch):
    _local_storage(monkeypatch, tmp_path)
    headers = await login(client, "+77012220001")
    await client.post("/api/v1/providers/me", headers=headers)

    # Без согласия на обработку ПДн загрузка запрещена.
    resp = await client.post(
        "/api/v1/me/documents",
        headers=headers,
        files={"file": ("spravka.pdf", PDF_STUB, "application/pdf")},
        data={"document_type": "criminal_record"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "consent_required"

    await _grant_consent(client, headers)

    # Справка eGov не в PDF — отказ.
    resp = await client.post(
        "/api/v1/me/documents",
        headers=headers,
        files={"file": ("scan.png", PNG_STUB, "image/png")},
        data={"document_type": "criminal_record"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "pdf_required"

    # Просроченная справка (выдана раньше норматива 90 дней) — отказ.
    old_date = (date.today() - timedelta(days=120)).isoformat()
    resp = await client.post(
        "/api/v1/me/documents",
        headers=headers,
        files={"file": ("spravka.pdf", PDF_STUB, "application/pdf")},
        data={"document_type": "criminal_record", "issued_at": old_date},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "document_expired"

    # Валидная загрузка: PDF + свежая дата. Удостоверение — картинкой можно.
    resp = await client.post(
        "/api/v1/me/documents",
        headers=headers,
        files={"file": ("spravka.pdf", PDF_STUB, "application/pdf")},
        data={
            "document_type": "criminal_record",
            "egov_reference": "KZ-123456",
            "issued_at": date.today().isoformat(),
        },
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/me/documents",
        headers=headers,
        files={"file": ("id.png", PNG_STUB, "image/png")},
        data={"document_type": "id_card"},
    )
    assert resp.status_code == 201, resp.text


async def test_decision_auto_validity_and_iin_linkage(
    client, session_factory, tmp_path, monkeypatch
):
    _local_storage(monkeypatch, tmp_path)
    headers = await login(client, "+77012220003")
    await client.post("/api/v1/providers/me", headers=headers)
    provider_id = (await client.get("/api/v1/me", headers=headers)).json()["id"]
    await _grant_consent(client, headers)

    async def upload(doc_type: str, name: str, content: bytes, mime: str) -> dict:
        resp = await client.post(
            "/api/v1/me/documents",
            headers=headers,
            files={"file": (name, content, mime)},
            data={"document_type": doc_type, "issued_at": date.today().isoformat()},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    id_card = await upload("id_card", "id.png", PNG_STUB, "image/png")
    criminal = await upload("criminal_record", "sudimost.pdf", PDF_STUB, "application/pdf")
    psych = await upload("psych_dispensary", "psych.pdf", PDF_STUB, "application/pdf")

    moderator = await login(client, "+77012220004")
    await _make_staff(session_factory, "+77012220004")

    # Одобряем удостоверение с ИИН.
    resp = await client.post(
        f"/api/v1/admin/documents/{id_card['id']}/decision",
        headers=moderator,
        json={"approve": True, "iin": "900101300123"},
    )
    assert resp.status_code == 200, resp.text

    # Несудимость: тот же ИИН → одобрено, срок действия проставлен автоматически (90 дней).
    resp = await client.post(
        f"/api/v1/admin/documents/{criminal['id']}/decision",
        headers=moderator,
        json={"approve": True, "iin": "900101300123"},
    )
    body = resp.json()
    assert body["status"] == "approved"
    expected = (date.today() + timedelta(days=90)).isoformat()
    assert body["valid_until"] == expected

    # Психдиспансер: ЧУЖОЙ ИИН → автоотказ (шаг 4 ТЗ 4.2).
    resp = await client.post(
        f"/api/v1/admin/documents/{psych['id']}/decision",
        headers=moderator,
        json={"approve": True, "iin": "850505400987"},
    )
    body = resp.json()
    assert body["status"] == "rejected"
    assert "ИИН" in body["rejection_reason"]

    # Журнал доступа пишется.
    async with session_factory() as session:
        count = await session.scalar(
            sa.select(sa.func.count()).select_from(DocumentAccessLog)
        )
        assert count >= 3

    # Наружу заказчику — только статус (проверим публичную карточку).
    customer = await login(client, "+77012220005")
    resp = await client.get(f"/api/v1/providers/{provider_id}", headers=customer)
    assert resp.status_code == 404 or "documents" not in resp.json()  # файлов в API карточки нет


async def test_expiry_worker_hides_profile(client, session_factory, tmp_path, monkeypatch):
    from app.models.enums import DocumentStatus, ProviderStatus
    from app.models.provider import ProviderProfile
    from app.models.verification import VerificationDocument
    from app.workers.documents import expire_stale_documents, send_expiry_reminders

    _local_storage(monkeypatch, tmp_path)
    headers = await login(client, "+77012220006")
    await client.post("/api/v1/providers/me", headers=headers)
    provider_id = uuid_module.UUID(
        (await client.get("/api/v1/me", headers=headers)).json()["id"]
    )

    async with session_factory() as session:
        # Активный профиль + одобренная справка, истекающая через 10 дней → напоминание «за 14».
        await session.execute(
            sa.update(ProviderProfile)
            .where(ProviderProfile.user_id == provider_id)
            .values(status=ProviderStatus.ACTIVE)
        )
        session.add(
            VerificationDocument(
                user_id=provider_id,
                document_type="criminal_record",
                storage_key="test/expiring.pdf",
                status=DocumentStatus.APPROVED,
                valid_until=date.today() + timedelta(days=10),
            )
        )
        await session.commit()

    async with session_factory() as session:
        sent = await send_expiry_reminders(session)
        await session.commit()
        assert sent == 1
        # Повторный запуск — без дублей.
        sent = await send_expiry_reminders(session)
        assert sent == 0

    # Просрочим справку и прогоним воркер: документ EXPIRED, профиль скрыт.
    async with session_factory() as session:
        await session.execute(
            sa.update(VerificationDocument)
            .where(VerificationDocument.user_id == provider_id)
            .values(valid_until=date.today() - timedelta(days=1))
        )
        await session.commit()

    async with session_factory() as session:
        expired = await expire_stale_documents(session)
        await session.commit()
        assert expired == 1

    async with session_factory() as session:
        profile = await session.get(ProviderProfile, provider_id)
        assert profile.status == ProviderStatus.PAUSED
