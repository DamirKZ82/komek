"""Общие FastAPI-зависимости: текущий пользователь, роли, пагинация."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError, ForbiddenError
from app.core.security import TokenError, decode_token
from app.db.session import get_session
from app.models.enums import StaffRole, UserStatus
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthError()
    try:
        payload = decode_token(credentials.credentials, "access")
    except TokenError as exc:
        raise AuthError(str(exc)) from exc

    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or user.status == UserStatus.DELETED:
        raise AuthError("Пользователь не найден")
    if user.status == UserStatus.SUSPENDED:
        raise ForbiddenError("Аккаунт приостановлен", code="account_suspended")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_provider(user: CurrentUser) -> User:
    if not user.is_provider:
        raise ForbiddenError("Доступно только исполнителям", code="provider_only")
    return user


CurrentProvider = Annotated[User, Depends(get_current_provider)]


async def get_current_staff(user: CurrentUser) -> User:
    if user.staff_role not in (StaffRole.MODERATOR, StaffRole.ADMIN):
        raise ForbiddenError()
    return user


CurrentStaff = Annotated[User, Depends(get_current_staff)]


@dataclass
class Pagination:
    limit: int
    offset: int


def get_pagination(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]
