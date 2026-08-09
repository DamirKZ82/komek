"""Сессии проверки личности у KYC-провайдера (п. 4.2 шаг 3, п. 4.3 ТЗ).

Результат проверки приходит от провайдера — вебхуком или опросом, — а не от
клиента. Клиент не может объявить себя проверенным: он лишь проходит сценарий
в мобильном SDK, а подтверждение личности опирается на сессию в этой таблице.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, enum_column
from app.models.enums import KycSessionStatus


class KycSession(Entity):
    __tablename__ = "kyc_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(sa.String(32))  # verigram | stub | ...
    # Идентификатор сессии на стороне провайдера — ключ сверки с вебхуком.
    provider_session_id: Mapped[str] = mapped_column(sa.String(128), unique=True, index=True)
    status: Mapped[KycSessionStatus] = mapped_column(
        enum_column(KycSessionStatus, "kyc_session_status"),
        default=KycSessionStatus.CREATED,
        index=True,
    )

    # Данные из документа: заполняются провайдером после успешной проверки.
    iin: Mapped[str | None] = mapped_column(sa.String(12), nullable=True)
    first_name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    birth_date: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    failure_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Сырой ответ провайдера — нужен при разборе спорных отказов.
    payload: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # Сессия уже использована для подтверждения личности — повторно нельзя.
    consumed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
