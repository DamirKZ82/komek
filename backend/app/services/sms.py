"""SMS-шлюз (п. 5.4 ТЗ).

В local/staging сообщения пишутся в лог — SMS не жгутся на тестах.
В проде используется HTTP-провайдер РК (Mobizon/SMSC и т.п.): заполните
SMS_API_URL и SMS_API_KEY, формат запроса подгоняется под выбранного провайдера.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger("komek.sms")


class SmsGateway(Protocol):
    async def send(self, phone: str, text: str) -> bool: ...


class LogSmsGateway:
    """Заглушка для разработки: пишет сообщение в лог и считает отправку успешной."""

    async def send(self, phone: str, text: str) -> bool:
        logger.info("SMS -> %s: %s", phone, text)
        return True


class HttpSmsGateway:
    """Универсальный HTTP-провайдер. Ошибка отправки не роняет бизнес-операцию."""

    async def send(self, phone: str, text: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    settings.sms_api_url,
                    json={
                        "recipient": phone,
                        "text": text,
                        "from": settings.sms_sender,
                    },
                    headers={"Authorization": f"Bearer {settings.sms_api_key}"},
                )
                response.raise_for_status()
            return True
        except Exception:  # noqa: BLE001 — SMS не должна ломать основной сценарий
            logger.warning("Не удалось отправить SMS на %s", phone, exc_info=True)
            return False


_gateway: SmsGateway | None = None


def get_sms_gateway() -> SmsGateway:
    global _gateway
    if _gateway is None:
        _gateway = HttpSmsGateway() if settings.sms_api_url else LogSmsGateway()
    return _gateway


async def send_sms(phone: str, text: str) -> bool:
    return await get_sms_gateway().send(phone, text)
