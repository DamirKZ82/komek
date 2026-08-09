"""Жизненный цикл заказа (п. 5.3 ТЗ) — единственное место, где меняется статус."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.datetime_utils import ensure_utc
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.catalog import Service
from app.models.enums import (
    CancelledBy,
    OrderResponseStatus,
    OrderSource,
    OrderStatus,
    PriceUnit,
    ProviderStatus,
)
from app.models.geo import Address
from app.models.order import Order, OrderResponse, OrderStatusHistory
from app.models.provider import ProviderProfile, ProviderService
from app.models.user import User
from app.schemas.order import CancelIn, CheckPointIn, OrderCreateIn, OrderResponseIn
from app.services.notifications import notify_user
from app.services.pricing import resolve_commission_rate

# Допустимые переходы: любое изменение статуса проверяется по этой карте.
_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.PUBLISHED, OrderStatus.SENT, OrderStatus.CANCELLED},
    OrderStatus.PUBLISHED: {OrderStatus.ACCEPTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED},
    OrderStatus.SENT: {OrderStatus.ACCEPTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED},
    OrderStatus.ACCEPTED: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: {OrderStatus.PAID},
    OrderStatus.PAID: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.EXPIRED: set(),
}


def _transition(
    order: Order, to_status: OrderStatus, actor_id: uuid.UUID | None, comment: str | None = None
) -> None:
    if to_status not in _TRANSITIONS[order.status]:
        raise ConflictError(
            f"Переход {order.status.value} → {to_status.value} невозможен",
            code="invalid_status_transition",
        )
    # Пишем историю через session напрямую: append в lazy-коллекцию у загруженного
    # заказа спровоцировал бы синхронный lazy-load внутри async-сессии.
    db = sa.orm.object_session(order)
    assert db is not None
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=order.status,
            to_status=to_status,
            actor_id=actor_id,
            comment=comment,
        )
    )
    order.status = to_status


def _order_code() -> str:
    year = datetime.now(UTC).year
    return f"K-{year}-{secrets.randbelow(10**6):06d}"


def _estimate_units(data: OrderCreateIn) -> Decimal:
    if data.price_unit == PriceUnit.HOUR:
        seconds = (data.scheduled_end - data.scheduled_start).total_seconds()
        return Decimal(str(round(seconds / 3600, 2)))
    return Decimal("1")


async def create_order(session: AsyncSession, customer: User, data: OrderCreateIn) -> Order:
    service = await session.get(Service, data.service_id)
    if service is None or not service.is_active:
        raise NotFoundError("Услуга не найдена")
    if data.price_unit.value not in service.allowed_price_units:
        raise ConflictError("Эта услуга не тарифицируется выбранным способом")

    unit_price = data.unit_price

    if data.provider_user_id is not None:
        # Сценарий «Каталог»: проверяем, что исполнитель активен и оказывает услугу.
        profile = await session.get(ProviderProfile, data.provider_user_id)
        if profile is None or profile.status != ProviderStatus.ACTIVE:
            raise NotFoundError("Исполнитель не найден или не принимает заказы")
        offer = await session.scalar(
            sa.select(ProviderService).where(
                ProviderService.provider_user_id == data.provider_user_id,
                ProviderService.service_id == data.service_id,
                ProviderService.price_unit == data.price_unit,
                ProviderService.is_active.is_(True),
            )
        )
        if offer is None:
            raise ConflictError("Исполнитель не оказывает эту услугу")
        unit_price = unit_price or offer.price

    if unit_price is None:
        raise ConflictError("Для заявки нужно указать цену", code="price_required")

    address = None
    if data.address_id is not None:
        address = await session.get(Address, data.address_id)
        if address is None or address.user_id != customer.id:
            raise NotFoundError("Адрес не найден")

    units = _estimate_units(data)
    now = datetime.now(UTC)
    is_urgent = (
        data.scheduled_start - now
    ).total_seconds() < settings.urgent_order_threshold_hours * 3600

    order = Order(
        code=_order_code(),
        customer_id=customer.id,
        provider_user_id=data.provider_user_id,
        service_id=data.service_id,
        source=OrderSource.CATALOG if data.provider_user_id else OrderSource.REQUEST,
        scheduled_start=data.scheduled_start,
        scheduled_end=data.scheduled_end,
        address_id=data.address_id,
        address_snapshot=address.as_snapshot() if address else None,
        city_id=address.city_id if address else customer.city_id,
        district_id=address.district_id if address else None,
        price_unit=data.price_unit,
        unit_price=unit_price,
        estimated_units=units,
        estimated_total=(unit_price * units).quantize(Decimal("0.01")),
        commission_rate=await resolve_commission_rate(session, data.service_id),
        comment=data.comment,
        details=data.details,
        required_qualification_ids=[str(q) for q in data.required_qualification_ids],
        is_urgent=is_urgent,
    )
    session.add(order)
    await session.flush()

    target = OrderStatus.SENT if data.provider_user_id else OrderStatus.PUBLISHED
    _transition(order, target, customer.id)
    order.published_at = now

    if data.provider_user_id is not None:
        await notify_user(
            session,
            data.provider_user_id,
            "Новый заказ",
            f"Вам предложили заказ {order.code}",
            {"order_id": str(order.id)},
        )
    return order


async def respond_to_order(
    session: AsyncSession, provider: User, order_id: uuid.UUID, data: OrderResponseIn
) -> OrderResponse:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise NotFoundError("Заказ не найден")
    if not order.is_open_for_responses:
        raise ConflictError("Заказ уже не принимает отклики")
    if order.customer_id == provider.id:
        raise ConflictError("Нельзя откликнуться на собственный заказ")

    existing = await session.scalar(
        sa.select(OrderResponse).where(
            OrderResponse.order_id == order_id,
            OrderResponse.provider_user_id == provider.id,
        )
    )
    if existing is not None:
        raise ConflictError("Вы уже откликнулись", code="already_responded")

    response = OrderResponse(
        order_id=order_id,
        provider_user_id=provider.id,
        offered_price=data.offered_price,
        message=data.message,
    )
    session.add(response)
    await notify_user(
        session,
        order.customer_id,
        "Новый отклик",
        f"На ваш заказ {order.code} откликнулся исполнитель",
        {"order_id": str(order.id)},
    )
    return response


async def accept_response(
    session: AsyncSession, customer: User, order_id: uuid.UUID, response_id: uuid.UUID
) -> Order:
    """Заказчик выбирает отклик — заказ закрепляется за исполнителем."""
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Заказ не найден")
    response = await session.get(OrderResponse, response_id)
    if response is None or response.order_id != order_id:
        raise NotFoundError("Отклик не найден")

    response.status = OrderResponseStatus.ACCEPTED
    order.provider_user_id = response.provider_user_id
    if response.offered_price is not None:
        order.unit_price = response.offered_price
        order.estimated_total = (response.offered_price * order.estimated_units).quantize(
            Decimal("0.01")
        )
    order.accepted_at = datetime.now(UTC)
    _transition(order, OrderStatus.ACCEPTED, customer.id)

    # Остальные отклики отклоняем.
    await session.execute(
        sa.update(OrderResponse)
        .where(
            OrderResponse.order_id == order_id,
            OrderResponse.id != response_id,
            OrderResponse.status == OrderResponseStatus.PENDING,
        )
        .values(status=OrderResponseStatus.DECLINED)
    )
    await notify_user(
        session,
        response.provider_user_id,
        "Вас выбрали!",
        f"Заказчик принял ваш отклик по заказу {order.code}",
        {"order_id": str(order.id)},
    )
    return order


async def accept_order(session: AsyncSession, provider: User, order_id: uuid.UUID) -> Order:
    """Исполнитель принимает прямое предложение (сценарий «Каталог»)."""
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None or order.provider_user_id != provider.id:
        raise NotFoundError("Заказ не найден")
    order.accepted_at = datetime.now(UTC)
    _transition(order, OrderStatus.ACCEPTED, provider.id)
    # Критическое событие: SMS, если у заказчика нет устройства для пуша (п. 5.4 ТЗ).
    await notify_user(
        session,
        order.customer_id,
        "Заказ принят",
        f"Исполнитель принял заказ {order.code}",
        {"order_id": str(order.id)},
        sms_fallback=True,
    )
    return order


async def confirm_order(session: AsyncSession, customer: User, order_id: uuid.UUID) -> Order:
    """Подтверждение найма: холд оплаты (типы B/C) или создание fee за подбор (тип A)."""
    from app.services.billing import setup_order_billing  # noqa: PLC0415 — разрыв цикла импортов

    order = await session.get(Order, order_id, with_for_update=True)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Заказ не найден")
    order.confirmed_at = datetime.now(UTC)
    _transition(order, OrderStatus.CONFIRMED, customer.id)
    await setup_order_billing(session, order)

    if order.provider_user_id is not None:
        await notify_user(
            session,
            order.provider_user_id,
            "Заказ подтверждён",
            f"Заказ {order.code} подтверждён — ждём вас в назначенное время",
            {"order_id": str(order.id)},
            sms_fallback=True,
        )
    return order


async def check_in(
    session: AsyncSession, provider: User, order_id: uuid.UUID, point: CheckPointIn
) -> Order:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None or order.provider_user_id != provider.id:
        raise NotFoundError("Заказ не найден")
    now = datetime.now(UTC)
    order.check_in_at = now
    order.actual_start = now
    order.check_in_latitude = point.latitude
    order.check_in_longitude = point.longitude
    _transition(order, OrderStatus.IN_PROGRESS, provider.id)
    return order


async def check_out(
    session: AsyncSession, provider: User, order_id: uuid.UUID, point: CheckPointIn
) -> Order:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None or order.provider_user_id != provider.id:
        raise NotFoundError("Заказ не найден")
    now = datetime.now(UTC)
    order.check_out_at = now
    order.actual_end = now
    order.check_out_latitude = point.latitude
    order.check_out_longitude = point.longitude
    order.completed_at = now

    # Фактические часы для почасовых заказов (п. 5.3 ТЗ), но не меньше
    # забронированного времени: слот исполнителя был зарезервирован целиком.
    if order.price_unit == PriceUnit.HOUR and order.actual_start is not None:
        seconds = (now - ensure_utc(order.actual_start)).total_seconds()
        actual_units = Decimal(str(round(seconds / 3600, 2)))
        order.final_units = max(actual_units, order.estimated_units)
    else:
        order.final_units = order.estimated_units
    order.final_total = (order.unit_price * order.final_units).quantize(Decimal("0.01"))
    order.commission_amount = (order.final_total * order.commission_rate).quantize(
        Decimal("0.01")
    )
    order.provider_payout_amount = order.final_total - order.commission_amount

    _transition(order, OrderStatus.COMPLETED, provider.id)

    await notify_user(
        session,
        order.customer_id,
        "Заказ завершён",
        f"Подтвердите оплату по заказу {order.code}",
        {"order_id": str(order.id)},
    )
    return order


def transition_to_paid(order: Order, actor_id: uuid.UUID | None = None) -> None:
    """Перевод в «оплачен» из вебхука эквайера — стейт-машина проверит допустимость."""
    _transition(order, OrderStatus.PAID, actor_id, comment="Подтверждено эквайером")


async def mark_paid(session: AsyncSession, customer: User, order_id: uuid.UUID) -> Order:
    """Оплата завершённого заказа (типы B/C). Списание — через billing (пока имитация)."""
    from app.services.billing import pay_order  # noqa: PLC0415 — разрыв цикла импортов

    order = await pay_order(session, customer, order_id)
    _transition(order, OrderStatus.PAID, customer.id)
    return order


async def cancel_order(
    session: AsyncSession, actor: User, order_id: uuid.UUID, data: CancelIn
) -> Order:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise NotFoundError("Заказ не найден")
    if actor.id == order.customer_id:
        by = CancelledBy.CUSTOMER
    elif actor.id == order.provider_user_id:
        by = CancelledBy.PROVIDER
    elif actor.is_staff:
        by = CancelledBy.PLATFORM
    else:
        raise ForbiddenError()

    # Штраф по правилам админа — только при отмене заказчиком (у него холд средств).
    # При отмене исполнителем или платформой заказчику возвращается всё.
    from app.services.billing import refund_order_hold  # noqa: PLC0415 — разрыв цикла
    from app.services.cancellation import calculate_penalty  # noqa: PLC0415

    penalty = Decimal("0")
    if by == CancelledBy.CUSTOMER:
        penalty = await calculate_penalty(session, order)
        if penalty > 0:
            order.cancellation_penalty = penalty

    # Возврат делаем до перевода в CANCELLED: если эквайер откажет, статус
    # платежа сохранит ошибку, а заказ всё равно закроется — деньги дособерёт сверка.
    if order.status in (OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS):
        await refund_order_hold(session, order, penalty)

    order.cancelled_at = datetime.now(UTC)
    order.cancelled_by = by
    order.cancellation_reason = data.reason
    _transition(order, OrderStatus.CANCELLED, actor.id, comment=data.reason)

    # Уведомляем вторую сторону.
    other_party = (
        order.provider_user_id if by == CancelledBy.CUSTOMER else order.customer_id
    )
    if other_party is not None and by != CancelledBy.PLATFORM:
        await notify_user(
            session,
            other_party,
            "Заказ отменён",
            f"Заказ {order.code} отменён: {data.reason}",
            {"order_id": str(order.id)},
        )
    return order
