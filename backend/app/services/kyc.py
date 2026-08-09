"""KYC-провайдер: liveness + распознавание удостоверения (п. 4.2 шаг 3 ТЗ).

Флоу, типовой для провайдеров (Verigram и аналоги):

1. Бэкенд создаёт сессию у провайдера и отдаёт клиенту её идентификатор/токен.
2. Мобильный SDK проводит liveness и съёмку документа по этому токену.
3. Результат приходит от провайдера — вебхуком или опросом статуса.
4. Личность подтверждается по сессии в нашей БД, а не по словам клиента.

Публичной документации у Verigram нет (доступ по договору), поэтому
VerigramKycProvider написан по этой типовой схеме: при подключении меняются
только URL и имена полей в _parse_result.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.models.enums import KycSessionStatus

logger = logging.getLogger("komek.kyc")


@dataclass(slots=True)
class KycSessionInit:
    """Что нужно клиенту, чтобы запустить SDK."""

    session_id: str
    # Токен/URL для SDK: у разных провайдеров называется по-разному.
    client_token: str | None = None
    sdk_url: str | None = None


@dataclass(slots=True)
class KycResult:
    status: KycSessionStatus
    iin: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    birth_date: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class KycProvider(Protocol):
    name: str

    async def create_session(self, user_id: str) -> KycSessionInit: ...

    async def fetch_result(self, session_id: str) -> KycResult: ...

    def parse_webhook(self, body: dict[str, Any]) -> tuple[str, KycResult]:
        """Возвращает (session_id, результат) из тела вебхука."""
        ...


class StubKycProvider:
    """Разработка без договора: сессия создаётся локально и сразу считается пройденной.

    ИИН берётся из идентификатора сессии, чтобы можно было тестировать связку
    «удостоверение ↔ справки» (шаг 4 флоу верификации).
    """

    name = "stub"

    async def create_session(self, user_id: str) -> KycSessionInit:
        return KycSessionInit(
            session_id=f"stub_{secrets.token_hex(8)}",
            client_token="stub-client-token",
        )

    async def fetch_result(self, session_id: str) -> KycResult:
        return KycResult(status=KycSessionStatus.PASSED, iin="900101300123")

    def parse_webhook(self, body: dict[str, Any]) -> tuple[str, KycResult]:
        session_id = str(body.get("session_id") or "")
        passed = bool(body.get("passed", True))
        return session_id, KycResult(
            status=KycSessionStatus.PASSED if passed else KycSessionStatus.FAILED,
            iin=body.get("iin"),
            reason=body.get("reason"),
            payload=body,
        )


class VerigramKycProvider:
    """Verigram (verigram.ai). Точные пути и поля уточняются при подключении договора."""

    name = "verigram"

    _STATUS_MAP = {
        "passed": KycSessionStatus.PASSED,
        "success": KycSessionStatus.PASSED,
        "approved": KycSessionStatus.PASSED,
        "failed": KycSessionStatus.FAILED,
        "declined": KycSessionStatus.FAILED,
        "rejected": KycSessionStatus.FAILED,
        "pending": KycSessionStatus.PENDING,
        "processing": KycSessionStatus.PENDING,
        "expired": KycSessionStatus.EXPIRED,
    }

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.request(
                    method,
                    f"{settings.kyc_api_url}{path}",
                    json=body,
                    headers={"Authorization": f"Bearer {settings.kyc_api_key}"},
                )
                response.raise_for_status()
                return response.json()
        except Exception:  # noqa: BLE001 — наружу отдаём понятный отказ
            logger.warning("KYC-провайдер недоступен: %s", path, exc_info=True)
            return None

    async def create_session(self, user_id: str) -> KycSessionInit:
        data = await self._request(
            "POST",
            "/sessions",
            {
                "external_id": user_id,
                "callback_url": settings.kyc_webhook_url,
                # Нужны обе проверки: живость и документ с извлечением ИИН.
                "checks": ["liveness", "document"],
            },
        )
        if not data:
            raise RuntimeError("Не удалось создать сессию проверки личности")
        return KycSessionInit(
            session_id=str(data.get("session_id") or data.get("id")),
            client_token=data.get("client_token") or data.get("token"),
            sdk_url=data.get("sdk_url"),
        )

    def _parse_result(self, data: dict[str, Any]) -> KycResult:
        document = data.get("document") or {}
        raw_status = str(data.get("status") or "").lower()
        return KycResult(
            status=self._STATUS_MAP.get(raw_status, KycSessionStatus.PENDING),
            iin=document.get("iin") or data.get("iin"),
            first_name=document.get("first_name"),
            last_name=document.get("last_name"),
            birth_date=document.get("birth_date"),
            reason=data.get("reason") or data.get("error_message"),
            payload=data,
        )

    async def fetch_result(self, session_id: str) -> KycResult:
        data = await self._request("GET", f"/sessions/{session_id}")
        if not data:
            return KycResult(
                status=KycSessionStatus.PENDING, reason="Сервис проверки недоступен"
            )
        return self._parse_result(data)

    def parse_webhook(self, body: dict[str, Any]) -> tuple[str, KycResult]:
        data = body.get("data") or body
        session_id = str(data.get("session_id") or data.get("id") or "")
        return session_id, self._parse_result(data)


_provider: KycProvider | None = None


def get_kyc_provider() -> KycProvider:
    global _provider
    if _provider is None:
        if settings.kyc_api_url:
            _provider = VerigramKycProvider()
        else:
            # Заглушка подтверждает личность без проверки — в проде это дыра.
            if settings.is_production:
                raise RuntimeError(
                    "KYC_API_URL не задан: в production заглушка запрещена"
                )
            _provider = StubKycProvider()
    return _provider
