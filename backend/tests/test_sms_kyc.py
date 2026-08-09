"""Тесты SMS-адаптера Mobizon, журнала отправок и вебхука KYC."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from tests.conftest import login


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.content = b"{}"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _fake_client(captured: dict[str, Any], payload: dict[str, Any]):
    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> FakeResponse:
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse(payload)

    return FakeClient


# --- SMS ----------------------------------------------------------------------


async def test_mobizon_send_and_journal(client, session_factory, monkeypatch):
    """Отправка через Mobizon: номер без «+», код 0 = успех, запись в журнал."""
    from app.models.enums import SmsStatus
    from app.models.messaging import SmsMessage
    from app.services import sms as sms_module

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        sms_module.httpx,
        "AsyncClient",
        _fake_client(captured, {"code": 0, "data": {"messageId": 55501}, "message": "ok"}),
    )
    monkeypatch.setattr(sms_module.settings, "sms_provider", "mobizon")
    monkeypatch.setattr(sms_module.settings, "sms_api_key", "mobizon-key")
    monkeypatch.setattr(sms_module, "_gateway", sms_module.MobizonSmsGateway())

    async with session_factory() as session:
        ok = await sms_module.send_sms(
            "+77011112233", "Komek: код 123456", session=session, purpose="otp"
        )
        await session.commit()
    assert ok is True

    # Mobizon требует номер без «+».
    assert captured["data"]["recipient"] == "77011112233"
    assert captured["data"]["apiKey"] == "mobizon-key"
    assert captured["url"].endswith("/Message/SendSmsMessage")

    async with session_factory() as session:
        record = await session.scalar(
            sa.select(SmsMessage).where(SmsMessage.phone == "+77011112233")
        )
        assert record is not None
        assert record.status == SmsStatus.SENT
        assert record.provider_message_id == "55501"
        assert record.purpose == "otp"
        # Текст с кодом в журнал не попадает.
        assert not hasattr(record, "text")


async def test_mobizon_error_code_is_failure(client, session_factory, monkeypatch):
    """Ненулевой code означает отказ — записываем ошибку, но не падаем."""
    from app.models.enums import SmsStatus
    from app.models.messaging import SmsMessage
    from app.services import sms as sms_module

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        sms_module.httpx,
        "AsyncClient",
        _fake_client(captured, {"code": 1, "message": "Invalid recipient"}),
    )
    monkeypatch.setattr(sms_module.settings, "sms_provider", "mobizon")
    monkeypatch.setattr(sms_module.settings, "sms_api_key", "mobizon-key")
    monkeypatch.setattr(sms_module, "_gateway", sms_module.MobizonSmsGateway())

    async with session_factory() as session:
        ok = await sms_module.send_sms("+77011112244", "текст", session=session)
        await session.commit()
    assert ok is False

    async with session_factory() as session:
        record = await session.scalar(
            sa.select(SmsMessage).where(SmsMessage.phone == "+77011112244")
        )
        assert record.status == SmsStatus.FAILED
        assert "Invalid recipient" in (record.error_message or "")


async def test_delivery_status_refresh(client, session_factory, monkeypatch):
    """Воркер подтягивает статус доставки и проставляет delivered_at."""
    from app.models.enums import SmsStatus
    from app.models.messaging import SmsMessage
    from app.services import sms as sms_module

    async with session_factory() as session:
        session.add(
            SmsMessage(
                phone="+77011112255",
                purpose="otp",
                provider="mobizon",
                status=SmsStatus.SENT,
                provider_message_id="777",
                sent_at=datetime.now(UTC),
            )
        )
        await session.commit()

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        sms_module.httpx,
        "AsyncClient",
        _fake_client(captured, {"code": 0, "data": [{"id": 777, "status": "DELIVRD"}]}),
    )
    monkeypatch.setattr(sms_module.settings, "sms_provider", "mobizon")
    monkeypatch.setattr(sms_module.settings, "sms_api_key", "mobizon-key")
    monkeypatch.setattr(sms_module, "_gateway", sms_module.MobizonSmsGateway())

    async with session_factory() as session:
        updated = await sms_module.refresh_delivery_statuses(session)
        await session.commit()
    assert updated == 1

    async with session_factory() as session:
        record = await session.scalar(
            sa.select(SmsMessage).where(SmsMessage.provider_message_id == "777")
        )
        assert record.status == SmsStatus.DELIVERED
        assert record.delivered_at is not None


async def test_otp_request_writes_journal(client, session_factory):
    """Запрос кода входа фиксируется в журнале — иначе не разобрать «код не пришёл»."""
    from app.models.messaging import SmsMessage

    resp = await client.post("/api/v1/auth/otp/request", json={"phone": "+77011113344"})
    assert resp.status_code == 200, resp.text

    async with session_factory() as session:
        record = await session.scalar(
            sa.select(SmsMessage).where(SmsMessage.phone == "+77011113344")
        )
        assert record is not None
        assert record.purpose == "otp"
        assert record.provider == "log"


# --- KYC ----------------------------------------------------------------------


def _signed(body: dict, secret: str) -> tuple[str, dict[str, str]]:
    raw = json.dumps(body)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw.encode(), hashlib.sha256
    ).hexdigest()
    return raw, {"X-Signature": signature, "X-Timestamp": timestamp}


async def test_kyc_webhook_marks_session_failed(client, session_factory, monkeypatch):
    """Отказ провайдера приходит вебхуком — подтвердить личность нельзя."""
    from app.core.config import settings
    from app.models.kyc import KycSession

    monkeypatch.setattr(settings, "kyc_webhook_secret", "kycsec")

    user = await login(client, "+77011114455")
    resp = await client.post("/api/v1/me/identity/session", headers=user)
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["session_id"]

    async with session_factory() as session:
        import uuid as uuid_module

        kyc = await session.get(KycSession, uuid_module.UUID(session_id))
        provider_session_id = kyc.provider_session_id

    body = {
        "event_id": "kyc_evt_1",
        "session_id": provider_session_id,
        "passed": False,
        "reason": "Лицо не совпадает с документом",
    }
    raw, headers = _signed(body, "kycsec")
    resp = await client.post("/api/v1/webhooks/kyc", content=raw, headers=headers)
    assert resp.status_code == 200, resp.text

    # Подтверждение по проваленной сессии отклоняется.
    resp = await client.post(
        "/api/v1/me/identity", headers=user, json={"session_id": session_id}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "kyc_failed"
    assert "не совпадает" in resp.json()["error"]["message"]


async def test_kyc_webhook_rejects_bad_signature(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "kyc_webhook_secret", "kycsec")

    body = {"event_id": "kyc_evt_2", "session_id": "x", "passed": True}
    resp = await client.post(
        "/api/v1/webhooks/kyc",
        content=json.dumps(body),
        headers={"X-Signature": "bad", "X-Timestamp": str(int(datetime.now(UTC).timestamp()))},
    )
    assert resp.status_code == 403


async def test_iin_cannot_be_reused_by_second_account(client):
    """Один ИИН — один аккаунт: заглушка выдаёт всем один ИИН, второй должен упасть."""
    first = await login(client, "+77011115566")
    resp = await client.post("/api/v1/me/identity/session", headers=first)
    resp = await client.post(
        "/api/v1/me/identity", headers=first, json={"session_id": resp.json()["session_id"]}
    )
    assert resp.status_code == 200, resp.text

    second = await login(client, "+77011115577")
    resp = await client.post("/api/v1/me/identity/session", headers=second)
    resp = await client.post(
        "/api/v1/me/identity", headers=second, json={"session_id": resp.json()["session_id"]}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "iin_already_used"
