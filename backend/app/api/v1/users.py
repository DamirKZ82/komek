from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import NotFoundError
from app.models.enums import DevicePlatform
from app.models.geo import Address
from app.models.user import Device, UserConsent
from app.schemas.common import Ok
from app.schemas.user import AddressIn, AddressOut, ConsentIn, UserOut, UserUpdateIn
from app.services import identity as identity_service

router = APIRouter(prefix="/me", tags=["me"])


class IdentityVerifyIn(BaseModel):
    """Токен сессии KYC-провайдера, полученный мобильным SDK на устройстве."""

    session_token: str = Field(min_length=4, max_length=512)


@router.post("/identity", response_model=UserOut)
async def verify_identity(
    data: IdentityVerifyIn, user: CurrentUser, session: SessionDep, request: Request
) -> UserOut:
    """Подтверждение личности: значок «проверенный» заказчику, уровень 1 исполнителю."""
    updated = await identity_service.verify_identity(
        session,
        user,
        data.session_token,
        request.client.host if request.client else None,
    )
    return UserOut.model_validate(updated)


class DeviceIn(BaseModel):
    platform: DevicePlatform
    push_token: str = Field(min_length=8, max_length=512)
    app_version: str | None = None


@router.post("/devices", response_model=Ok)
async def register_device(data: DeviceIn, user: CurrentUser, session: SessionDep) -> Ok:
    """Регистрация push-токена. Токен уникален: при смене владельца переезжает."""
    existing = await session.scalar(
        sa.select(Device).where(Device.push_token == data.push_token)
    )
    if existing is not None:
        existing.user_id = user.id
        existing.platform = data.platform
        existing.app_version = data.app_version
        existing.is_active = True
    else:
        session.add(
            Device(
                user_id=user.id,
                platform=data.platform,
                push_token=data.push_token,
                app_version=data.app_version,
            )
        )
    return Ok()


@router.get("", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("", response_model=UserOut)
async def update_me(data: UserUpdateIn, user: CurrentUser, session: SessionDep) -> UserOut:
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field_name, value)
    session.add(user)
    return UserOut.model_validate(user)


@router.post("/consents", response_model=Ok)
async def grant_consent(
    data: ConsentIn, user: CurrentUser, session: SessionDep, request: Request
) -> Ok:
    session.add(
        UserConsent(
            user_id=user.id,
            consent_type=data.consent_type,
            document_version=data.document_version,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    return Ok()


@router.get("/addresses", response_model=list[AddressOut])
async def list_addresses(user: CurrentUser, session: SessionDep) -> list[AddressOut]:
    rows = await session.scalars(
        sa.select(Address)
        .where(Address.user_id == user.id, Address.is_archived.is_(False))
        .order_by(Address.is_default.desc(), Address.created_at.desc())
    )
    return [AddressOut.model_validate(a) for a in rows]


@router.post("/addresses", response_model=AddressOut, status_code=201)
async def create_address(data: AddressIn, user: CurrentUser, session: SessionDep) -> AddressOut:
    if data.is_default:
        await session.execute(
            sa.update(Address).where(Address.user_id == user.id).values(is_default=False)
        )
    address = Address(user_id=user.id, **data.model_dump())
    session.add(address)
    await session.flush()
    return AddressOut.model_validate(address)


@router.delete("/addresses/{address_id}", response_model=Ok)
async def delete_address(address_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Ok:
    address = await session.get(Address, address_id)
    if address is None or address.user_id != user.id:
        raise NotFoundError("Адрес не найден")
    address.is_archived = True  # мягкое удаление: адрес мог попасть в снимки заказов
    return Ok()
