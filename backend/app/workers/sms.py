"""Воркер статусов доставки SMS.

Провайдер узнаёт о доставке не сразу, поэтому статус подтягивается опросом.
Запуск: python -m app.workers.sms (планировать каждые 5–10 минут).
"""

from __future__ import annotations

import asyncio
import logging

from app.db.session import async_session_factory
from app.services.sms import refresh_delivery_statuses

logger = logging.getLogger("komek.workers.sms")


async def main() -> None:
    async with async_session_factory() as session:
        updated = await refresh_delivery_statuses(session)
        await session.commit()
    logger.info("Обновлено статусов SMS: %s", updated)
    print(f"Обновлено статусов SMS: {updated}")


if __name__ == "__main__":
    asyncio.run(main())
