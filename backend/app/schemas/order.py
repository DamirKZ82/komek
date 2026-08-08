from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    CancelledBy,
    OrderResponseStatus,
    OrderSource,
    OrderStatus,
    PriceUnit,
)
from app.schemas.common import ApiModel


class OrderCreateIn(BaseModel):
    service_id: uuid.UUID
    # Если исполнитель указан — сценарий «Каталог», иначе публикуется заявка.
    provider_user_id: uuid.UUID | None = None
    scheduled_start: datetime
    scheduled_end: datetime
    address_id: uuid.UUID | None = None
    price_unit: PriceUnit = PriceUnit.HOUR
    # Для заявки заказчик может назвать свою ставку; для каталога берётся прайс исполнителя.
    unit_price: Decimal | None = Field(default=None, gt=0)
    comment: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    required_qualification_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_window(self) -> OrderCreateIn:
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end должен быть позже scheduled_start")
        return self


class OrderResponseIn(BaseModel):
    offered_price: Decimal | None = Field(default=None, gt=0)
    message: str | None = Field(default=None, max_length=1000)


class OrderResponseOut(ApiModel):
    id: uuid.UUID
    order_id: uuid.UUID
    provider_user_id: uuid.UUID
    status: OrderResponseStatus
    offered_price: Decimal | None
    message: str | None
    responded_at: datetime


class CheckPointIn(BaseModel):
    """Чек-ин/чек-аут с координатами — только при выданном согласии на гео."""

    latitude: float | None = None
    longitude: float | None = None


class CancelIn(BaseModel):
    reason: str = Field(max_length=500)


class OrderOut(ApiModel):
    id: uuid.UUID
    code: str
    customer_id: uuid.UUID
    provider_user_id: uuid.UUID | None
    service_id: uuid.UUID
    source: OrderSource
    status: OrderStatus
    is_urgent: bool
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    address_snapshot: dict[str, Any] | None
    district_id: uuid.UUID | None
    price_unit: PriceUnit
    unit_price: Decimal
    estimated_units: Decimal
    estimated_total: Decimal
    final_units: Decimal | None
    final_total: Decimal | None
    commission_rate: Decimal
    commission_amount: Decimal | None
    provider_payout_amount: Decimal | None
    currency: str
    comment: str | None
    details: dict[str, Any]
    check_in_at: datetime | None
    check_out_at: datetime | None
    cancelled_by: CancelledBy | None
    cancellation_reason: str | None
    cancellation_penalty: Decimal | None
    responses_count: int = 0
    created_at: datetime
