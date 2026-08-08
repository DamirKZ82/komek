"""Пуш-уведомления через Expo Push API (п. 5.4 ТЗ).

Приложение собрано на Expo, поэтому вместо прямой интеграции FCM/APNS используется
Expo Push Service: токены вида ExponentPushToken[...] шлются на exp.host.
Отправка — best-effort: ошибка пуша никогда не роняет бизнес-операцию.
Очередь задач (п. 6 ТЗ) появится при росте нагрузки — интерфейс не изменится.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Device, User
from app.services.sms import send_sms

logger = logging.getLogger("komek.push")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


async def _send_expo_batch(messages: list[dict[str, Any]]) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(EXPO_PUSH_URL, json=messages)
        response.raise_for_status()


async def notify_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    *,
    sms_fallback: bool = False,
) -> None:
    """Пуш на все активные устройства пользователя. Никогда не бросает.

    При sms_fallback=True и отсутствии устройств отправляет SMS — для критических
    событий вроде подтверждения заказа (п. 5.4 ТЗ).
    """
    try:
        devices = (
            await session.scalars(
                sa.select(Device).where(
                    Device.user_id == user_id, Device.is_active.is_(True)
                )
            )
        ).all()
        if not devices:
            if sms_fallback:
                user = await session.get(User, user_id)
                if user is not None:
                    await send_sms(user.phone, f"{title}. {body}")
            return

        expo_messages = []
        for device in devices:
            if device.push_token.startswith("ExponentPushToken"):
                expo_messages.append(
                    {
                        "to": device.push_token,
                        "title": title,
                        "body": body,
                        "data": data or {},
                        "sound": "default",
                    }
                )
            else:
                # Не-Expo токен (например, dev-заглушка) — только лог.
                logger.info("PUSH (лог) -> %s: %s — %s", device.push_token[:24], title, body)

        if expo_messages:
            await _send_expo_batch(expo_messages)
    except Exception:  # noqa: BLE001 — пуш не должен ломать бизнес-операцию
        logger.warning("Не удалось отправить пуш пользователю %s", user_id, exc_info=True)
