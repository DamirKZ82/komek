"""Верификация исполнителей — ядро продукта (раздел 4 ТЗ).

Документы физически лежат в отдельном шифруемом бакете; в БД только метаданные,
статус и журнал доступа. Заказчику наружу отдаётся исключительно статус и срок годности.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, enum_column
from app.models.enums import (
    DocumentStatus,
    DocumentType,
    InterviewType,
    VerificationLevel,
    VerificationRequestStatus,
)


class VerificationDocument(Entity):
    __tablename__ = "verification_documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        enum_column(DocumentType, "document_type"), index=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        enum_column(DocumentStatus, "document_status"), default=DocumentStatus.PENDING, index=True
    )

    storage_key: Mapped[str] = mapped_column(sa.String(512))  # ключ в закрытом бакете
    file_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    file_size: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    # Реквизиты справки eGov: номер/QR, по которому модератор проверяет подлинность.
    egov_reference: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    # ИИН из документа (модератор/KYC): для связки «удостоверение ↔ справки» (шаг 4 ТЗ 4.2).
    iin: Mapped[str | None] = mapped_column(sa.String(12), nullable=True)
    issued_at: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(sa.Date, nullable=True, index=True)
    # Отметки отправленных напоминаний об истечении (значения из настроек: 14, 3).
    reminders_sent: Mapped[list[int]] = mapped_column(sa.JSON, default=list)

    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    @property
    def is_expired(self) -> bool:
        return self.valid_until is not None and self.valid_until < date.today()


class VerificationRequest(Entity):
    """Заявка исполнителя на присвоение уровня — очередь модерации (п. 5.7 ТЗ)."""

    __tablename__ = "verification_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    target_level: Mapped[VerificationLevel] = mapped_column(
        enum_column(VerificationLevel, "target_verification_level")
    )
    status: Mapped[VerificationRequestStatus] = mapped_column(
        enum_column(VerificationRequestStatus, "verification_request_status"),
        default=VerificationRequestStatus.SUBMITTED,
        index=True,
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    # Чек-лист модератора: {"documents_match": true, "interview_passed": true, ...}
    checklist: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    moderator_notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    interviews: Mapped[list[VerificationInterview]] = relationship(back_populates="request")


class VerificationInterview(Entity):
    """Видеозвонок 10–15 минут или загруженная видеовизитка (уровень 2)."""

    __tablename__ = "verification_interviews"

    request_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("verification_requests.id", ondelete="CASCADE"), index=True
    )
    interview_type: Mapped[InterviewType] = mapped_column(
        enum_column(InterviewType, "interview_type")
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    conducted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    recording_key: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    moderator_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    passed: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    request: Mapped[VerificationRequest] = relationship(back_populates="interviews")


class DocumentAccessLog(Entity):
    """Журналирование доступа к документам — требование Закона РК о ПДн (п. 6 ТЗ)."""

    __tablename__ = "document_access_logs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("verification_documents.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(sa.String(32))  # view | download | decide
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
