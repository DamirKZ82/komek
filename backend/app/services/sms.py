"""SMS-шлюз (п. 5.4 ТЗ).

Провайдер выбирается настройкой SMS_PROVIDER:
- `log` (по умолчанию вне production) — сообщение пишется в лог, SMS не жгутся на тестах;
- `mobizon` — Mobizon (api.mobizon.kz), популярный шлюз в РК;
- `http` — универсальный POST-адаптер под любого другого провайдера.

Каждая отправка пишется в журнал sms_messages: без него нельзя разобрать
жалобу «код не пришёл». Текст сообщения в журнал не попадает — в нём код входа.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import SmsStatus
from app.models.messaging import SmsMessage

logger = logging.getLogger("komek.sms")

MOBIZON_BASE_URL = "https://api.mobizon.kz/service"


@dataclass(slots=True)
class SmsResult:
    success: bool
    provider_message_id: str | None = None
    error_message: str | None = None


class SmsGateway(Protocol):
    name: str

    async def send(self, phone: str, text: str) -> SmsResult: ...

    async def check_statuses(self, message_ids: list[str]) -> dict[str, SmsStatus]:
        """Опрос статусов доставки. Провайдер может не поддерживать — тогда пусто."""
        ...


class LogSmsGateway:
    """Заглушка для разработки: пишет сообщение в лог и считает отправку успешной."""

    name = "log"

    async def send(self, phone: str, text: str) -> SmsResult:
        logger.info("SMS -> %s: %s", phone, text)
        return SmsResult(success=True, provider_message_id=None)

    async def check_statuses(self, message_ids: list[str]) -> dict[str, SmsStatus]:
        return {}


class MobizonSmsGateway:
    """Mobizon: https://mobizon.kz/help/api-docs/message

    Ответ приходит в виде {"code": 0, "data": {...}, "message": "..."},
    где code=0 означает успех.
    """

    name = "mobizon"

    # Коды статусов Mobizon приводим к нашим.
    _STATUS_MAP = {
        "DELIVRD": SmsStatus.DELIVERED,
        "ACCEPTD": SmsStatus.SENT,
        "ENROUTE": SmsStatus.SENT,
        "EXPIRED": SmsStatus.EXPIRED,
        "UNDELIV": SmsStatus.FAILED,
        "REJECTD": SmsStatus.FAILED,
        "DELETED": SmsStatus.FAILED,
        "UNKNOWN": SmsStatus.SENT,
    }

    async def send(self, phone: str, text: str) -> SmsResult:
        # Mobizon ждёт номер без «+», только цифры.
        recipient = phone.lstrip("+")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{MOBIZON_BASE_URL}/Message/SendSmsMessage",
                    params={"output": "json", "api": "v1"},
                    data={
                        "recipient": recipient,
                        "text": text,
                        "from": settings.sms_sender,
                        "apiKey": settings.sms_api_key,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001 — SMS не должна ломать основной сценарий
            logger.warning("Mobizon недоступен", exc_info=True)
            return SmsResult(success=False, error_message=str(exc))

        if payload.get("code") != 0:
            message = payload.get("message") or "Mobizon отклонил сообщение"
            logger.warning("Mobizon вернул ошибку: %s", message)
            return SmsResult(success=False, error_message=str(message))

        data = payload.get("data") or {}
        return SmsResult(success=True, provider_message_id=str(data.get("messageId") or ""))

    async def check_statuses(self, message_ids: list[str]) -> dict[str, SmsStatus]:
        if not message_ids:
            return {}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{MOBIZON_BASE_URL}/Message/GetSMSStatus",
                    params={"output": "json", "api": "v1"},
                    data={
                        # За раз Mobizon принимает не более 100 идентификаторов.
                        "ids": ",".join(message_ids[:100]),
                        "apiKey": settings.sms_api_key,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось опросить статусы Mobizon", exc_info=True)
            return {}

        if payload.get("code") != 0:
            return {}

        result: dict[str, SmsStatus] = {}
        for item in payload.get("data") or []:
            message_id = str(item.get("id") or "")
            raw_status = str(item.get("status") or "").upper()
            if message_id:
                result[message_id] = self._STATUS_MAP.get(raw_status, SmsStatus.SENT)
        return result


class HttpSmsGateway:
    """Универсальный провайдер: JSON-POST. Поля подгоняются под документацию."""

    name = "http"

    async def send(self, phone: str, text: str) -> SmsResult:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    settings.sms_api_url,
                    json={"recipient": phone, "text": text, "from": settings.sms_sender},
                    headers={"Authorization": f"Bearer {settings.sms_api_key}"},
                )
                response.raise_for_status()
                data = response.json() if response.content else {}
            return SmsResult(success=True, provider_message_id=str(data.get("id") or "") or None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SMS-провайдер недоступен", exc_info=True)
            return SmsResult(success=False, error_message=str(exc))

    async def check_statuses(self, message_ids: list[str]) -> dict[str, SmsStatus]:
        return {}


_gateway: SmsGateway | None = None


def get_sms_gateway() -> SmsGateway:
    global _gateway
    if _gateway is None:
        provider = (settings.sms_provider or "").lower()
        if provider == "mobizon" and settings.sms_api_key:
            _gateway = MobizonSmsGateway()
        elif provider == "http" and settings.sms_api_url:
            _gateway = HttpSmsGateway()
        else:
            if settings.is_production:
                # Иначе коды входа молча уходили бы в лог, и войти никто не смог бы.
                raise RuntimeError(
                    "SMS_PROVIDER не настроен: в production заглушка запрещена"
                )
            _gateway = LogSmsGateway()
    return _gateway


async def send_sms(
    phone: str,
    text: str,
    *,
    session: AsyncSession | None = None,
    purpose: str = "system",
) -> bool:
    """Отправка с журналированием. Никогда не бросает — SMS вторична к сценарию."""
    gateway = get_sms_gateway()
    result = await gateway.send(phone, text)

    if session is not None:
        session.add(
            SmsMessage(
                phone=phone,
                purpose=purpose,
                provider=gateway.name,
                status=SmsStatus.SENT if result.success else SmsStatus.FAILED,
                provider_message_id=result.provider_message_id or None,
                error_message=result.error_message,
                sent_at=datetime.now(UTC) if result.success else None,
            )
        )
    return result.success


async def refresh_delivery_statuses(session: AsyncSession, limit: int = 100) -> int:
    """Опрашивает провайдера по отправленным SMS без финального статуса."""
    pending = (
        await session.scalars(
            sa.select(SmsMessage)
            .where(
                SmsMessage.status == SmsStatus.SENT,
                SmsMessage.provider_message_id.is_not(None),
            )
            .order_by(SmsMessage.created_at.desc())
            .limit(limit)
        )
    ).all()
    if not pending:
        return 0

    statuses = await get_sms_gateway().check_statuses(
        [m.provider_message_id for m in pending if m.provider_message_id]
    )
    now = datetime.now(UTC)
    updated = 0
    for message in pending:
        new_status = statuses.get(message.provider_message_id or "")
        message.status_checked_at = now
        if new_status is None or new_status == message.status:
            continue
        message.status = new_status
        if new_status == SmsStatus.DELIVERED:
            message.delivered_at = now
        updated += 1
    return updated
