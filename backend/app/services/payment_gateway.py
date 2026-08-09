"""Платёжный шлюз (п. 5.5 ТЗ): холдирование → списание → возврат.

Провайдер (Kaspi Pay / эквайринг банка) изолирован за интерфейсом PaymentGateway.
Подключение боевого эквайера = заполнить PAYMENT_API_URL/PAYMENT_API_KEY и, при
необходимости, поправить маппинг полей в HttpPaymentGateway — остальной код не меняется.

В разработке работает SandboxGateway: он не ходит в сеть и сразу возвращает успешный
результат с синтетическим psp_reference. В production он запрещён (см. get_payment_gateway).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger("komek.payments")


@dataclass(slots=True)
class GatewayResult:
    """Ответ шлюза. `pending=True` — итог придёт вебхуком, а не синхронно."""

    success: bool
    psp_reference: str | None = None
    pending: bool = False
    card_mask: str | None = None
    # Ссылка на страницу оплаты/приложение Kaspi — клиент открывает её.
    confirmation_url: str | None = None
    error_message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class PaymentGateway(Protocol):
    async def authorize(
        self, *, amount: Decimal, currency: str, idempotency_key: str, description: str
    ) -> GatewayResult:
        """Захолдировать сумму на карте плательщика."""
        ...

    async def capture(
        self, *, psp_reference: str, amount: Decimal, idempotency_key: str
    ) -> GatewayResult:
        """Списать ранее захолдированную сумму (может быть меньше холда)."""
        ...

    async def refund(
        self, *, psp_reference: str, amount: Decimal, idempotency_key: str
    ) -> GatewayResult:
        """Вернуть деньги полностью или частично."""
        ...

    async def payout(
        self, *, amount: Decimal, destination: str, idempotency_key: str
    ) -> GatewayResult:
        """Выплата исполнителю на карту/Kaspi."""
        ...


class SandboxPaymentGateway:
    """Для разработки и тестов: успешный ответ без обращения к сети."""

    async def authorize(
        self, *, amount: Decimal, currency: str, idempotency_key: str, description: str
    ) -> GatewayResult:
        logger.info("SANDBOX authorize %s %s (%s)", amount, currency, description)
        return GatewayResult(
            success=True,
            psp_reference=f"sbx_{secrets.token_hex(8)}",
            card_mask="4400 ** 1234",
        )

    async def capture(
        self, *, psp_reference: str, amount: Decimal, idempotency_key: str
    ) -> GatewayResult:
        logger.info("SANDBOX capture %s на %s", psp_reference, amount)
        return GatewayResult(success=True, psp_reference=psp_reference)

    async def refund(
        self, *, psp_reference: str, amount: Decimal, idempotency_key: str
    ) -> GatewayResult:
        logger.info("SANDBOX refund %s на %s", psp_reference, amount)
        return GatewayResult(success=True, psp_reference=psp_reference)

    async def payout(
        self, *, amount: Decimal, destination: str, idempotency_key: str
    ) -> GatewayResult:
        logger.info("SANDBOX payout %s -> %s", amount, destination)
        return GatewayResult(success=True, psp_reference=f"sbxpo_{secrets.token_hex(8)}")


class HttpPaymentGateway:
    """Боевой эквайер. Имена полей — типовые; сверьте с документацией провайдера."""

    async def _post(self, path: str, body: dict[str, Any], idempotency_key: str) -> GatewayResult:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{settings.payment_api_url}{path}",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {settings.payment_api_key}",
                        # Защита от двойного списания при ретраях.
                        "Idempotency-Key": idempotency_key,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            logger.warning("Эквайер вернул ошибку %s: %s", exc.response.status_code, detail)
            return GatewayResult(success=False, error_message=detail)
        except Exception as exc:  # noqa: BLE001 — сеть/таймаут: платёж не проведён
            logger.warning("Эквайер недоступен", exc_info=True)
            return GatewayResult(success=False, error_message=str(exc))

        status = str(data.get("status", "")).lower()
        return GatewayResult(
            success=status in {"ok", "success", "approved", "pending", "processing"},
            pending=status in {"pending", "processing"},
            psp_reference=data.get("id") or data.get("transaction_id"),
            card_mask=data.get("card_mask"),
            confirmation_url=data.get("confirmation_url"),
            error_message=data.get("error_message"),
            payload=data,
        )

    async def authorize(
        self, *, amount: Decimal, currency: str, idempotency_key: str, description: str
    ) -> GatewayResult:
        return await self._post(
            "/payments/authorize",
            {
                "amount": str(amount),
                "currency": currency,
                "description": description,
                "capture": False,  # только холд, списание — после чек-аута
                "callback_url": settings.payment_webhook_url,
            },
            idempotency_key,
        )

    async def capture(
        self, *, psp_reference: str, amount: Decimal, idempotency_key: str
    ) -> GatewayResult:
        return await self._post(
            f"/payments/{psp_reference}/capture", {"amount": str(amount)}, idempotency_key
        )

    async def refund(
        self, *, psp_reference: str, amount: Decimal, idempotency_key: str
    ) -> GatewayResult:
        return await self._post(
            f"/payments/{psp_reference}/refund", {"amount": str(amount)}, idempotency_key
        )

    async def payout(
        self, *, amount: Decimal, destination: str, idempotency_key: str
    ) -> GatewayResult:
        return await self._post(
            "/payouts",
            {"amount": str(amount), "destination": destination},
            idempotency_key,
        )


_gateway: PaymentGateway | None = None


def get_payment_gateway() -> PaymentGateway:
    global _gateway
    if _gateway is None:
        if settings.payment_api_url:
            _gateway = HttpPaymentGateway()
        else:
            # Песочница «подтверждает» любой платёж — в проде это означало бы
            # бесплатные заказы, поэтому конфигурация обязана быть заполнена.
            if settings.is_production:
                raise RuntimeError(
                    "PAYMENT_API_URL не задан: в production песочница запрещена"
                )
            _gateway = SandboxPaymentGateway()
    return _gateway
