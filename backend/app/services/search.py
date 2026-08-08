"""Поиск исполнителей с фильтрами из п. 5.1 ТЗ."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import Language, PriceUnit, ProviderStatus, VerificationLevel
from app.models.provider import (
    Favorite,
    ProviderDistrict,
    ProviderLanguage,
    ProviderProfile,
    ProviderQualification,
    ProviderService,
)
from app.models.user import User
from app.schemas.provider import ProviderCard


@dataclass
class ProviderSearchQuery:
    service_id: uuid.UUID | None = None
    city_id: uuid.UUID | None = None
    district_ids: list[uuid.UUID] = field(default_factory=list)
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    price_unit: PriceUnit | None = None
    min_verification: VerificationLevel | None = None
    min_experience_years: int | None = None
    min_rating: Decimal | None = None
    languages: list[Language] = field(default_factory=list)
    qualification_ids: list[uuid.UUID] = field(default_factory=list)
    urgent_only: bool = False
    sort: str = "rating"  # rating | price | experience
    limit: int = 20
    offset: int = 0


async def search_providers(
    session: AsyncSession, query: ProviderSearchQuery, viewer_id: uuid.UUID | None = None
) -> tuple[list[ProviderCard], int]:
    stmt = (
        sa.select(ProviderProfile)
        .join(User, User.id == ProviderProfile.user_id)
        .where(ProviderProfile.status == ProviderStatus.ACTIVE)
        .options(
            selectinload(ProviderProfile.user),
            selectinload(ProviderProfile.services),
            selectinload(ProviderProfile.languages),
        )
    )

    if query.city_id is not None:
        stmt = stmt.where(ProviderProfile.city_id == query.city_id)
    if query.min_experience_years is not None:
        stmt = stmt.where(ProviderProfile.experience_years >= query.min_experience_years)
    if query.min_rating is not None:
        stmt = stmt.where(ProviderProfile.rating_avg >= query.min_rating)
    if query.urgent_only:
        stmt = stmt.where(ProviderProfile.accepts_urgent.is_(True))
    if query.min_verification is not None:
        allowed = [
            level for level in VerificationLevel if level.rank >= query.min_verification.rank
        ]
        stmt = stmt.where(ProviderProfile.verification_level.in_(allowed))

    if query.service_id is not None or query.price_min or query.price_max or query.price_unit:
        offer = (
            sa.select(ProviderService.provider_user_id)
            .where(ProviderService.is_active.is_(True))
        )
        if query.service_id is not None:
            offer = offer.where(ProviderService.service_id == query.service_id)
        if query.price_unit is not None:
            offer = offer.where(ProviderService.price_unit == query.price_unit)
        if query.price_min is not None:
            offer = offer.where(ProviderService.price >= query.price_min)
        if query.price_max is not None:
            offer = offer.where(ProviderService.price <= query.price_max)
        stmt = stmt.where(ProviderProfile.user_id.in_(offer))

    if query.district_ids:
        stmt = stmt.where(
            ProviderProfile.user_id.in_(
                sa.select(ProviderDistrict.provider_user_id).where(
                    ProviderDistrict.district_id.in_(query.district_ids)
                )
            )
        )

    if query.languages:
        stmt = stmt.where(
            ProviderProfile.user_id.in_(
                sa.select(ProviderLanguage.provider_user_id).where(
                    ProviderLanguage.language.in_(query.languages)
                )
            )
        )

    for qual_id in query.qualification_ids:
        stmt = stmt.where(
            ProviderProfile.user_id.in_(
                sa.select(ProviderQualification.provider_user_id).where(
                    ProviderQualification.qualification_id == qual_id
                )
            )
        )

    total = await session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    )

    if query.sort == "experience":
        stmt = stmt.order_by(ProviderProfile.experience_years.desc())
    elif query.sort == "price":
        min_price = (
            sa.select(sa.func.min(ProviderService.price))
            .where(
                ProviderService.provider_user_id == ProviderProfile.user_id,
                ProviderService.is_active.is_(True),
            )
            .correlate(ProviderProfile)
            .scalar_subquery()
        )
        stmt = stmt.order_by(min_price.asc().nulls_last())
    else:
        # rating по умолчанию; «профессионалы» выше (п. 4.1: приоритет в выдаче).
        stmt = stmt.order_by(
            ProviderProfile.verification_level.desc(),
            ProviderProfile.rating_avg.desc().nulls_last(),
            ProviderProfile.rating_count.desc(),
        )

    stmt = stmt.limit(query.limit).offset(query.offset)
    profiles = (await session.scalars(stmt)).all()

    favorite_ids: set[uuid.UUID] = set()
    if viewer_id is not None and profiles:
        favorite_ids = set(
            (
                await session.scalars(
                    sa.select(Favorite.provider_user_id).where(
                        Favorite.customer_id == viewer_id,
                        Favorite.provider_user_id.in_([p.user_id for p in profiles]),
                    )
                )
            ).all()
        )

    cards = [build_card(profile, profile.user_id in favorite_ids) for profile in profiles]
    return cards, int(total or 0)


def build_card(profile: ProviderProfile, is_favorite: bool = False) -> ProviderCard:
    active_offers = [s for s in profile.services if s.is_active]
    min_offer = min(active_offers, key=lambda s: s.price, default=None)
    return ProviderCard(
        user_id=profile.user_id,
        first_name=profile.user.first_name,
        last_name=profile.user.last_name,
        avatar_key=profile.user.avatar_key,
        headline=profile.headline,
        verification_level=profile.verification_level,
        experience_years=profile.experience_years,
        rating_avg=profile.rating_avg,
        rating_count=profile.rating_count,
        completed_orders_count=profile.completed_orders_count,
        response_time_minutes=profile.response_time_minutes,
        min_price=min_offer.price if min_offer else None,
        price_unit=min_offer.price_unit if min_offer else None,
        accepts_urgent=profile.accepts_urgent,
        languages=[pl.language for pl in profile.languages],
        is_favorite=is_favorite,
    )
