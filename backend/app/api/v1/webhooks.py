"""Приём вебхуков эквайринга (п. 5.5 ТЗ).

Безопасность: подпись HMAC-SHA256 от сырого тела запроса + метка времени.
Без настроенного PAYMENT_WEBHOOK_SECRET эндпоинт не принимает ничего в production —
иначе кто угодно мог бы объявить заказ оплаченным.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Header, Request

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.errors import AppError, ForbiddenError
from app.models.enums import OrderStatus, PaymentStatus
from app.models.kyc import KycSession
from app.models.order import Order
from app.models.payment import Payment
from app.models.webhook import WebhookEvent
from app.schemas.common import Ok
from app.services.identity import apply_result
from app.services.kyc import get_kyc_provider
from app.services.notifications import notify_user
from app.services.orders import transition_to_paid

logger = logging.getLogger("komek.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(
    raw_body: bytes,
    signature: str | None,
    timestamp: str | None,
    secret: str | None = None,
) -> None:
    if secret is None:
        secret = settings.payment_webhook_secret
    if not secret:
        if settings.is_production:
            raise ForbiddenError(
                "Приём вебхуков не настроен", code="webhook_secret_missing"
            )
        return  # в local/staging подпись не требуем

    if not signature or not timestamp:
        raise ForbiddenError("Отсутствует подпись вебхука", code="webhook_signature_missing")

    # Защита от replay: старые события отбрасываем.
    try:
        sent_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (TypeError, ValueError) as exc:
        raise ForbiddenError("Некорректная метка времени", code="webhook_bad_timestamp") from exc
    age = abs((datetime.now(UTC) - sent_at).total_seconds())
    if age > settings.payment_webhook_max_age_seconds:
        raise ForbiddenError("Вебхук устарел", code="webhook_expired")

    expected = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ForbiddenError("Подпись вебхука неверна", code="webhook_bad_signature")


async def _apply_payment_event(
    session: SessionDep, event_type: str, data: dict[str, Any]
) -> None:
    """Приводит платёж и заказ в состояние, о котором сообщил эквайер."""
    psp_reference = data.get("id") or data.get("transaction_id")
    if not psp_reference:
        raise AppError("В событии нет идентификатора платежа", code="webhook_no_reference")

    payment = await session.scalar(
        sa.select(Payment).where(Payment.psp_reference == str(psp_reference))
    )
    if payment is None:
        # Платёж мог быть создан другим окружением — фиксируем, но не падаем.
        logger.warning("Вебхук по неизвестному платежу %s", psp_reference)
        return

    now = datetime.now(UTC)
    order = await session.get(Order, payment.order_id, with_for_update=True)

    if event_type in {"payment.authorized", "payment.hold"}:
        payment.status = PaymentStatus.HELD
        payment.held_at = payment.held_at or now
        if data.get("card_mask"):
            payment.card_mask = data["card_mask"]

    elif event_type in {"payment.captured", "payment.succeeded"}:
        payment.status = PaymentStatus.CAPTURED
        payment.captured_at = payment.captured_at or now
        payment.captured_amount = payment.captured_amount or payment.amount
        # Заказ переводим в «оплачен» только из «завершён» — стейт-машина проверит.
        if order is not None and order.status == OrderStatus.COMPLETED:
            order.paid_at = now
            transition_to_paid(order)
            if order.provider_user_id is not None:
                await notify_user(
                    session,
                    order.provider_user_id,
                    "Заказ оплачен",
                    f"Заказ {order.code} оплачен, выплата будет в ближайшем реестре",
                    {"order_id": str(order.id)},
                )

    elif event_type in {"payment.refunded", "payment.reversed"}:
        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = payment.refunded_at or now
        payment.refunded_amount = payment.amount

    elif event_type in {"payment.failed", "payment.declined"}:
        payment.status = PaymentStatus.FAILED
        payment.error_message = data.get("error_message") or "Платёж отклонён"
        if order is not None and order.status == OrderStatus.COMPLETED:
            await notify_user(
                session,
                order.customer_id,
                "Оплата не прошла",
                f"Не удалось списать оплату по заказу {order.code}",
                {"order_id": str(order.id)},
                sms_fallback=True,
            )
    else:
        logger.info("Неизвестный тип события эквайера: %s", event_type)


@router.post("/payments", response_model=Ok)
async def payment_webhook(
    request: Request,
    session: SessionDep,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
) -> Ok:
    raw_body = await request.body()
    _verify_signature(raw_body, x_signature, x_timestamp)

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise AppError("Тело вебхука не является JSON", code="webhook_bad_body") from exc

    event_id = str(body.get("event_id") or body.get("id") or "")
    if not event_id:
        raise AppError("В событии нет event_id", code="webhook_no_event_id")
    event_type = str(body.get("type") or body.get("event") or "")

    # Идемпотентность: повтор того же события не меняет состояние повторно.
    existing = await session.scalar(
        sa.select(WebhookEvent).where(
            WebhookEvent.source == "payments", WebhookEvent.event_id == event_id
        )
    )
    if existing is not None:
        return Ok()

    event = WebhookEvent(
        source="payments", event_id=event_id, event_type=event_type, payload=body
    )
    session.add(event)
    await session.flush()

    data = body.get("data") or body.get("object") or body
    await _apply_payment_event(session, event_type, data)
    event.processed_at = datetime.now(UTC)
    return Ok()


@router.post("/kyc", response_model=Ok)
async def kyc_webhook(
    request: Request,
    session: SessionDep,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
    x_timestamp: Annotated[str | None, Header(alias="X-Timestamp")] = None,
) -> Ok:
    """Результат проверки личности от KYC-провайдера (п. 4.2 шаг 3 ТЗ)."""
    raw_body = await request.body()
    _verify_signature(raw_body, x_signature, x_timestamp, settings.kyc_webhook_secret)

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise AppError("Тело вебхука не является JSON", code="webhook_bad_body") from exc

    provider = get_kyc_provider()
    provider_session_id, result = provider.parse_webhook(body)
    if not provider_session_id:
        raise AppError("В событии нет идентификатора сессии", code="webhook_no_session")

    event_id = str(body.get("event_id") or f"kyc-{provider_session_id}-{result.status.value}")
    existing = await session.scalar(
        sa.select(WebhookEvent).where(
            WebhookEvent.source == "kyc", WebhookEvent.event_id == event_id
        )
    )
    if existing is not None:
        return Ok()

    event = WebhookEvent(
        source="kyc", event_id=event_id, event_type=result.status.value, payload=body
    )
    session.add(event)

    kyc_session = await session.scalar(
        sa.select(KycSession).where(KycSession.provider_session_id == provider_session_id)
    )
    if kyc_session is None:
        logger.warning("Вебхук по неизвестной KYC-сессии %s", provider_session_id)
        return Ok()

    await apply_result(session, kyc_session, result)
    event.processed_at = datetime.now(UTC)
    return Ok()
