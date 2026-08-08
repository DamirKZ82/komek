from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import DocumentStatus, DocumentType
from app.schemas.common import ApiModel


class DocumentOut(ApiModel):
    id: uuid.UUID
    document_type: DocumentType
    status: DocumentStatus
    file_name: str | None
    content_type: str | None
    file_size: int | None
    egov_reference: str | None
    issued_at: date | None
    valid_until: date | None
    rejection_reason: str | None
    created_at: datetime


class DocumentDecisionIn(BaseModel):
    approve: bool
    # Срок действия; если не указан — считается автоматически по нормативу типа справки.
    valid_until: date | None = None
    # ИИН из документа: модератор вносит вручную (позже — из KYC/QR автоматически).
    # Несовпадение с ИИН удостоверения того же исполнителя = автоотказ (шаг 4 ТЗ 4.2).
    iin: str | None = Field(default=None, min_length=12, max_length=12, pattern=r"^\d{12}$")
    rejection_reason: str | None = Field(default=None, max_length=1000)
