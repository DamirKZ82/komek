from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ReviewDirection, ReviewStatus
from app.schemas.common import ApiModel


class ReviewCreateIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    rating_punctuality: int | None = Field(default=None, ge=1, le=5)
    rating_attitude: int | None = Field(default=None, ge=1, le=5)
    rating_communication: int | None = Field(default=None, ge=1, le=5)
    text: str | None = Field(default=None, max_length=2000)


class ReviewReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ReviewOut(ApiModel):
    id: uuid.UUID
    order_id: uuid.UUID
    author_id: uuid.UUID
    target_id: uuid.UUID
    direction: ReviewDirection
    rating: int
    rating_punctuality: int | None
    rating_attitude: int | None
    rating_communication: int | None
    text: str | None
    status: ReviewStatus
    reply_text: str | None
    reply_at: datetime | None
    published_at: datetime | None
    editable_until: datetime | None
    created_at: datetime
