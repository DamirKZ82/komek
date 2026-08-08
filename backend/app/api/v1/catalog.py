from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Query
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep
from app.models.catalog import Qualification, Service, ServiceCategory
from app.models.enums import Locale, Vertical
from app.models.geo import City, District
from app.schemas.catalog import (
    CategoryOut,
    CityOut,
    DistrictOut,
    Localized,
    QualificationOut,
    ServiceOut,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])

LocaleQ = Annotated[Locale, Query()]


def _service_out(service: Service, locale: Locale) -> ServiceOut:
    return ServiceOut(
        id=service.id,
        category_id=service.category_id,
        code=service.code,
        name=Localized.pick(service, "name", locale),
        description=getattr(service, f"description_{locale.value}", None)
        or service.description_ru,
        allowed_price_units=service.allowed_price_units,
        min_duration_minutes=service.min_duration_minutes,
        supports_urgent=service.supports_urgent,
        required_verification_rank=service.required_verification_rank,
    )


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    session: SessionDep, locale: LocaleQ = Locale.RU, vertical: Vertical | None = None
) -> list[CategoryOut]:
    stmt = (
        sa.select(ServiceCategory)
        .where(ServiceCategory.is_active.is_(True))
        .options(selectinload(ServiceCategory.services))
        .order_by(ServiceCategory.sort_order)
    )
    if vertical is not None:
        stmt = stmt.where(ServiceCategory.vertical == vertical)
    categories = (await session.scalars(stmt)).all()
    return [
        CategoryOut(
            id=c.id,
            code=c.code,
            vertical=c.vertical,
            name=Localized.pick(c, "name", locale),
            icon=c.icon,
            services=[
                _service_out(s, locale)
                for s in sorted(c.services, key=lambda s: s.sort_order)
                if s.is_active
            ],
        )
        for c in categories
    ]


@router.get("/qualifications", response_model=list[QualificationOut])
async def list_qualifications(
    session: SessionDep, locale: LocaleQ = Locale.RU, vertical: Vertical | None = None
) -> list[QualificationOut]:
    stmt = (
        sa.select(Qualification)
        .where(Qualification.is_active.is_(True))
        .order_by(Qualification.sort_order)
    )
    if vertical is not None:
        stmt = stmt.where(
            sa.or_(Qualification.vertical == vertical, Qualification.vertical.is_(None))
        )
    rows = (await session.scalars(stmt)).all()
    return [
        QualificationOut(
            id=q.id,
            code=q.code,
            vertical=q.vertical,
            name=Localized.pick(q, "name", locale),
            requires_document=q.requires_document,
        )
        for q in rows
    ]


@router.get("/cities", response_model=list[CityOut])
async def list_cities(session: SessionDep, locale: LocaleQ = Locale.RU) -> list[CityOut]:
    rows = (
        await session.scalars(sa.select(City).order_by(City.sort_order))
    ).all()
    return [
        CityOut(
            id=c.id,
            code=c.code,
            name=Localized.pick(c, "name", locale),
            latitude=c.latitude,
            longitude=c.longitude,
            is_active=c.is_active,
        )
        for c in rows
    ]


@router.get("/cities/{city_id}/districts", response_model=list[DistrictOut])
async def list_districts(
    city_id: uuid.UUID, session: SessionDep, locale: LocaleQ = Locale.RU
) -> list[DistrictOut]:
    rows = (
        await session.scalars(
            sa.select(District)
            .where(District.city_id == city_id, District.is_active.is_(True))
            .order_by(District.name_ru)
        )
    ).all()
    return [
        DistrictOut(
            id=d.id, city_id=d.city_id, code=d.code, name=Localized.pick(d, "name", locale)
        )
        for d in rows
    ]
