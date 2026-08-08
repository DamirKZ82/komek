"""Подбор постоянного исполнителя — тип A монетизации (п. 5.8 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.models.enums import PlacementFeeStatus
from app.models.placement import Placement
from app.schemas.common import ApiModel
from app.services import billing

router = APIRouter(prefix="/placements", tags=["placements"])


class PlacementOut(ApiModel):
    id: uuid.UUID
    order_id: uuid.UUID
    provider_user_id: uuid.UUID
    monthly_rate: Decimal
    fee_amount: Decimal
    fee_status: PlacementFeeStatus
    fee_paid_at: datetime | None
    guarantee_until: datetime | None
    replacement_requested_at: datetime | None
    replacement_of_id: uuid.UUID | None
    created_at: datetime


class ReplacementIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


def _out(placement: Placement) -> PlacementOut:
    return PlacementOut.model_validate(placement)


@router.get("/my", response_model=list[PlacementOut])
async def my_placements(user: CurrentUser, session: SessionDep) -> list[PlacementOut]:
    return [_out(p) for p in await billing.get_my_placements(session, user)]


@router.post("/{placement_id}/pay", response_model=PlacementOut)
async def pay_fee(
    placement_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> PlacementOut:
    """Оплата fee за подбор. Включает гарантию замены на 30 дней."""
    return _out(await billing.pay_placement_fee(session, user, placement_id))


@router.post("/{placement_id}/replacement", response_model=PlacementOut)
async def request_replacement(
    placement_id: uuid.UUID, data: ReplacementIn, user: CurrentUser, session: SessionDep
) -> PlacementOut:
    """Запрос бесплатной замены по гарантии: следующий подбор — без fee."""
    return _out(await billing.request_replacement(session, user, placement_id, data.reason))
