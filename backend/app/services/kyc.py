"""Проверка личности через KYC-провайдера (п. 4.2 шаг 3, п. 4.3 ТЗ).

Схема по ТЗ: мобильный SDK провайдера (Verigram или аналог, работающий в РК)
проводит liveness и распознаёт удостоверение, затем отдаёт клиенту токен сессии.
Бэкенд обменивает токен на результат проверки — здесь эта точка изолирована.

Пока договор с провайдером не заключён, работает StubKycProvider: он принимает
любой токен и возвращает ИИН, переданный клиентом. Включать в production нельзя —
`verify_identity` это проверяет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger("komek.kyc")


@dataclass(slots=True)
class KycResult:
    passed: bool
    iin: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    birth_date: str | None = None
    reason: str | None = None


class KycProvider(Protocol):
    async def check_session(self, session_token: str) -> KycResult: ...


class StubKycProvider:
    """Заглушка для разработки: доверяет данным клиента, ничего не проверяет."""

    async def check_session(self, session_token: str) -> KycResult:
        logger.info("KYC-заглушка: сессия %s принята без проверки", session_token[:12])
        # Формат dev-токена: "stub:<ИИН>" — позволяет тестировать связку по ИИН.
        iin = session_token.removeprefix("stub:") if session_token.startswith("stub:") else None
        return KycResult(passed=True, iin=iin)


class HttpKycProvider:
    """Боевой провайдер: обмен токена сессии на результат проверки."""

    async def check_session(self, session_token: str) -> KycResult:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{settings.kyc_api_url}/sessions/verify",
                    json={"session_token": session_token},
                    headers={"Authorization": f"Bearer {settings.kyc_api_key}"},
                )
                response.raise_for_status()
                data = response.json()
        except Exception:  # noqa: BLE001 — наружу отдаём понятный отказ
            logger.warning("KYC-провайдер недоступен", exc_info=True)
            return KycResult(passed=False, reason="Сервис проверки временно недоступен")

        return KycResult(
            passed=bool(data.get("passed")),
            iin=data.get("iin"),
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            birth_date=data.get("birth_date"),
            reason=data.get("reason"),
        )


_provider: KycProvider | None = None


def get_kyc_provider() -> KycProvider:
    global _provider
    if _provider is None:
        _provider = HttpKycProvider() if settings.kyc_api_url else StubKycProvider()
    return _provider
