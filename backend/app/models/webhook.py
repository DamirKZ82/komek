"""Журнал входящих вебхуков — обеспечивает идемпотентность обработки."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity


class WebhookEvent(Entity):
    """Эквайер повторяет callback до подтверждения — повторы не должны менять состояние дважды."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        sa.UniqueConstraint("source", "event_id", name="uq_webhook_events_source_event"),
    )

    source: Mapped[str] = mapped_column(sa.String(32), index=True)  # payments | ...
    event_id: Mapped[str] = mapped_column(sa.String(128))
    event_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    processed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
