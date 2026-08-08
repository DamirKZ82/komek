from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import (
    ComplaintCategory,
    ComplaintStatus,
    VerificationLevel,
    VerificationRequestStatus,
)
from app.schemas.common import ApiModel


class VerificationSubmitIn(BaseModel):
    target_level: VerificationLevel = VerificationLevel.VERIFIED


class VerificationRequestOut(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID
    target_level: VerificationLevel
    status: VerificationRequestStatus
    submitted_at: datetime
    decided_at: datetime | None
    rejection_reason: str | None


class VerificationDecisionIn(BaseModel):
    approve: bool
    # Чек-лист модератора (п. 5.7 ТЗ): что именно проверено.
    checklist: dict[str, bool] = Field(default_factory=dict)
    rejection_reason: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class ComplaintIn(BaseModel):
    target_user_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    category: ComplaintCategory
    description: str = Field(min_length=10, max_length=4000)


class ComplaintOut(ApiModel):
    id: uuid.UUID
    reporter_id: uuid.UUID | None
    target_user_id: uuid.UUID | None
    order_id: uuid.UUID | None
    category: ComplaintCategory
    status: ComplaintStatus
    description: str
    resolution: str | None
    auto_suspended: bool
    created_at: datetime


class ComplaintResolveIn(BaseModel):
    resolution: str = Field(min_length=3, max_length=2000)
    dismiss: bool = False
    compensation_amount: Decimal | None = None
