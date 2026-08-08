"""Воркер сроков действия справок (п. 4.2 ТЗ).

- За 14 и 3 дня до истечения: пуш «обновите справку».
- По истечении: документ → EXPIRED, профиль автоматически скрывается из поиска
  (PAUSED, не удаляется) до загрузки и одобрения свежей справки.

Запуск: python -m app.workers.documents (планировать cron'ом раз в день).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.enums import DocumentStatus, ProviderStatus
from app.models.provider import ProviderProfile
from app.models.verification import VerificationDocument
from app.services.notifications import notify_user

logger = logging.getLogger("komek.workers.documents")

# Типы справок, без действующей версии которых профиль скрывается из поиска.
REQUIRED_CERTIFICATE_TYPES = [
    "criminal_record",
    "psych_dispensary",
    "narco_dispensary",
]


async def send_expiry_reminders(session: AsyncSession) -> int:
    """Пуши за N дней до истечения. Возвращает число отправленных напоминаний."""
    today = date.today()
    sent = 0
    for days in settings.document_expiry_reminder_days:
        target = today + timedelta(days=days)
        documents = (
            await session.scalars(
                sa.select(VerificationDocument).where(
                    VerificationDocument.status == DocumentStatus.APPROVED,
                    VerificationDocument.valid_until <= target,
                    VerificationDocument.valid_until > today,
                )
            )
        ).all()
        for document in documents:
            if days in (document.reminders_sent or []):
                continue
            await notify_user(
                session,
                document.user_id,
                "Обновите справку",
                f"Срок действия справки истекает {document.valid_until:%d.%m.%Y} — "
                "получите свежую в eGov и загрузите в приложение",
            )
            document.reminders_sent = [*(document.reminders_sent or []), days]
            sent += 1
    return sent


async def expire_stale_documents(session: AsyncSession) -> int:
    """Помечает просроченные документы и скрывает профили без действующих справок."""
    today = date.today()
    expired_docs = (
        await session.scalars(
            sa.select(VerificationDocument).where(
                VerificationDocument.status == DocumentStatus.APPROVED,
                VerificationDocument.valid_until < today,
            )
        )
    ).all()
    affected_users = set()
    for document in expired_docs:
        document.status = DocumentStatus.EXPIRED
        affected_users.add(document.user_id)

    for user_id in affected_users:
        profile = await session.get(ProviderProfile, user_id)
        if profile is None or profile.status != ProviderStatus.ACTIVE:
            continue
        # Есть ли действующая замена по каждому обязательному типу?
        valid_types = set(
            (
                await session.scalars(
                    sa.select(VerificationDocument.document_type).where(
                        VerificationDocument.user_id == user_id,
                        VerificationDocument.status == DocumentStatus.APPROVED,
                        VerificationDocument.valid_until >= today,
                    )
                )
            ).all()
        )
        missing = [t for t in REQUIRED_CERTIFICATE_TYPES if t not in valid_types]
        if missing:
            profile.status = ProviderStatus.PAUSED
            await notify_user(
                session,
                user_id,
                "Анкета скрыта из поиска",
                "Истёк срок справки. Загрузите свежую — анкета вернётся после проверки",
            )
    return len(expired_docs)


async def main() -> None:
    async with async_session_factory() as session:
        reminders = await send_expiry_reminders(session)
        expired = await expire_stale_documents(session)
        await session.commit()
    logger.info("Напоминаний: %s, просрочено документов: %s", reminders, expired)
    print(f"Напоминаний отправлено: {reminders}; документов просрочено: {expired}")


if __name__ == "__main__":
    asyncio.run(main())
