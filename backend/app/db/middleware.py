"""Сессия БД на запрос с коммитом ДО отправки ответа.

Почему не зависимость с yield: начиная с FastAPI 0.106 код после `yield`
выполняется уже после того, как ответ ушёл клиенту. Если коммитить там,
клиент получает 200 раньше, чем данные оказываются в БД, — и следующий
запрос их не находит. Для пары «запросить код → подтвердить код» это
воспроизводимая гонка.

Middleware оборачивает обработчик целиком, поэтому коммит гарантированно
происходит до того, как клиент увидит ответ. Сессия открывается лениво:
запросы без обращения к БД (health-check, 404, статика) соединение не тратят.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.db.session import async_session_factory

_STATE_ATTR = "db_session_holder"


class _SessionHolder:
    """Держит сессию запроса и открывает её при первом обращении."""

    def __init__(self) -> None:
        self.session: AsyncSession | None = None

    def get(self) -> AsyncSession:
        if self.session is None:
            self.session = async_session_factory()
        return self.session

    async def finish(self, *, commit: bool) -> None:
        if self.session is None:
            return
        try:
            if commit:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()


class DatabaseSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        holder = _SessionHolder()
        setattr(request.state, _STATE_ATTR, holder)
        try:
            response = await call_next(request)
        except Exception:
            await holder.finish(commit=False)
            raise

        # Ошибочные ответы не должны сохранять частичные изменения.
        await holder.finish(commit=response.status_code < 400)
        return response


def get_request_session(request: Request) -> AsyncSession:
    """FastAPI-зависимость: сессия, привязанная к текущему запросу."""
    holder: _SessionHolder | None = getattr(request.state, _STATE_ATTR, None)
    if holder is None:  # pragma: no cover — middleware не подключён
        raise RuntimeError("DatabaseSessionMiddleware не подключён к приложению")
    return holder.get()
