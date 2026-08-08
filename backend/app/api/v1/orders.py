from __future__ import annotations

import uuid
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentProvider, CurrentUser, PaginationDep, SessionDep
from app.core.errors import ForbiddenError, NotFoundError
from app.models.enums import OrderStatus, ProviderStatus
from app.models.order import Order
from app.models.provider import ProviderProfile
from app.schemas.common import Page
from app.schemas.order import (
    CancelIn,
    CheckPointIn,
    OrderCreateIn,
    OrderOut,
    OrderResponseIn,
    OrderResponseOut,
)
from app.services import orders as order_service

router = APIRouter(prefix="/orders", tags=["orders"])


def _out(order: Order) -> OrderOut:
    dto = OrderOut.model_validate(order)
    dto.responses_count = len(order.responses)
    return dto


async def _get_order(session: SessionDep, order_id: uuid.UUID) -> Order:
    order = await session.scalar(
        sa.select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.responses))
    )
    if order is None:
        raise NotFoundError("Заказ не найден")
    return order


@router.post("", response_model=OrderOut, status_code=201)
async def create_order(data: OrderCreateIn, user: CurrentUser, session: SessionDep) -> OrderOut:
    order = await order_service.create_order(session, user, data)
    await session.refresh(order, ["responses"])
    return _out(order)


@router.get("/my", response_model=Page[OrderOut])
async def my_orders(
    user: CurrentUser,
    session: SessionDep,
    pagination: PaginationDep,
    role: Literal["customer", "provider"] = "customer",
    status: OrderStatus | None = None,
) -> Page[OrderOut]:
    field = Order.customer_id if role == "customer" else Order.provider_user_id
    stmt = sa.select(Order).where(field == user.id).options(selectinload(Order.responses))
    if status is not None:
        stmt = stmt.where(Order.status == status)
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = (
        await session.scalars(
            stmt.order_by(Order.scheduled_start.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
    ).all()
    return Page(
        items=[_out(o) for o in rows],
        total=int(total or 0),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/feed", response_model=Page[OrderOut])
async def open_orders_feed(
    user: CurrentProvider, session: SessionDep, pagination: PaginationDep
) -> Page[OrderOut]:
    """Лента открытых заявок для исполнителя (биржевой сценарий)."""
    profile = await session.get(ProviderProfile, user.id)
    if profile is None or profile.status != ProviderStatus.ACTIVE:
        raise ForbiddenError("Анкета ещё не прошла модерацию", code="profile_not_active")

    stmt = (
        sa.select(Order)
        .where(Order.status == OrderStatus.PUBLISHED, Order.provider_user_id.is_(None))
        .options(selectinload(Order.responses))
    )
    if profile.city_id is not None:
        stmt = stmt.where(sa.or_(Order.city_id == profile.city_id, Order.city_id.is_(None)))
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = (
        await session.scalars(
            stmt.order_by(Order.is_urgent.desc(), Order.scheduled_start.asc())
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
    ).all()
    return Page(
        items=[_out(o) for o in rows],
        total=int(total or 0),
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OrderOut:
    order = await _get_order(session, order_id)
    is_party = user.id in (order.customer_id, order.provider_user_id)
    is_responder = any(r.provider_user_id == user.id for r in order.responses)
    if not (is_party or is_responder or user.is_staff or order.is_open_for_responses):
        raise NotFoundError("Заказ не найден")
    return _out(order)


@router.post("/{order_id}/responses", response_model=OrderResponseOut, status_code=201)
async def respond(
    order_id: uuid.UUID, data: OrderResponseIn, user: CurrentProvider, session: SessionDep
) -> OrderResponseOut:
    response = await order_service.respond_to_order(session, user, order_id, data)
    await session.flush()
    return OrderResponseOut.model_validate(response)


@router.get("/{order_id}/responses", response_model=list[OrderResponseOut])
async def list_responses(
    order_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[OrderResponseOut]:
    order = await _get_order(session, order_id)
    if order.customer_id != user.id and not user.is_staff:
        raise ForbiddenError()
    return [OrderResponseOut.model_validate(r) for r in order.responses]


@router.post("/{order_id}/responses/{response_id}/accept", response_model=OrderOut)
async def accept_response(
    order_id: uuid.UUID, response_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> OrderOut:
    order = await order_service.accept_response(session, user, order_id, response_id)
    await session.refresh(order, ["responses"])
    return _out(order)


@router.post("/{order_id}/accept", response_model=OrderOut)
async def accept_direct(
    order_id: uuid.UUID, user: CurrentProvider, session: SessionDep
) -> OrderOut:
    order = await order_service.accept_order(session, user, order_id)
    await session.refresh(order, ["responses"])
    return _out(order)


@router.post("/{order_id}/confirm", response_model=OrderOut)
async def confirm(order_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OrderOut:
    order = await order_service.confirm_order(session, user, order_id)
    await session.refresh(order, ["responses"])
    return _out(order)


@router.post("/{order_id}/check-in", response_model=OrderOut)
async def check_in(
    order_id: uuid.UUID, data: CheckPointIn, user: CurrentProvider, session: SessionDep
) -> OrderOut:
    order = await order_service.check_in(session, user, order_id, data)
    await session.refresh(order, ["responses"])
    return _out(order)


@router.post("/{order_id}/check-out", response_model=OrderOut)
async def check_out(
    order_id: uuid.UUID, data: CheckPointIn, user: CurrentProvider, session: SessionDep
) -> OrderOut:
    order = await order_service.check_out(session, user, order_id, data)
    await session.refresh(order, ["responses"])
    return _out(order)


@router.post("/{order_id}/pay", response_model=OrderOut)
async def pay(order_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OrderOut:
    """Оплата завершённого заказа (типы B/C). До эквайринга — имитация списания."""
    order = await order_service.mark_paid(session, user, order_id)
    await session.refresh(order, ["responses"])
    return _out(order)


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel(
    order_id: uuid.UUID, data: CancelIn, user: CurrentUser, session: SessionDep
) -> OrderOut:
    order = await order_service.cancel_order(session, user, order_id, data)
    await session.refresh(order, ["responses"])
    return _out(order)
