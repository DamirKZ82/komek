from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentProvider, CurrentUser, PaginationDep, SessionDep
from app.core.errors import ConflictError, NotFoundError
from app.models.enums import (
    Language,
    PriceUnit,
    ProviderStatus,
    VerificationLevel,
)
from app.models.provider import (
    Favorite,
    ProviderDistrict,
    ProviderLanguage,
    ProviderProfile,
    ProviderQualification,
    ProviderService,
    ProviderWeeklySlot,
)
from app.schemas.common import Ok, Page
from app.schemas.moderation import VerificationRequestOut, VerificationSubmitIn
from app.schemas.provider import (
    ProviderCard,
    ProviderDetail,
    ProviderProfileUpdateIn,
    ProviderServiceIn,
    ProviderServiceOut,
    WeeklySlotIn,
    WeeklySlotOut,
)
from app.services import moderation as moderation_service
from app.services.search import ProviderSearchQuery, build_card, search_providers

router = APIRouter(prefix="/providers", tags=["providers"])


def _search_query(
    pagination: PaginationDep,
    service_id: uuid.UUID | None = None,
    city_id: uuid.UUID | None = None,
    district_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
    price_min: Decimal | None = None,
    price_max: Decimal | None = None,
    price_unit: PriceUnit | None = None,
    min_verification: VerificationLevel | None = None,
    min_experience_years: int | None = None,
    min_rating: Decimal | None = None,
    languages: Annotated[list[Language] | None, Query()] = None,
    qualification_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
    urgent_only: bool = False,
    sort: str = "rating",
) -> ProviderSearchQuery:
    return ProviderSearchQuery(
        service_id=service_id,
        city_id=city_id,
        district_ids=district_ids or [],
        price_min=price_min,
        price_max=price_max,
        price_unit=price_unit,
        min_verification=min_verification,
        min_experience_years=min_experience_years,
        min_rating=min_rating,
        languages=languages or [],
        qualification_ids=qualification_ids or [],
        urgent_only=urgent_only,
        sort=sort,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/search", response_model=Page[ProviderCard])
async def search(
    session: SessionDep,
    user: CurrentUser,
    query: Annotated[ProviderSearchQuery, Depends(_search_query)],
) -> Page[ProviderCard]:
    cards, total = await search_providers(session, query, viewer_id=user.id)
    return Page(items=cards, total=total, limit=query.limit, offset=query.offset)


async def _load_profile(session: SessionDep, user_id: uuid.UUID) -> ProviderProfile:
    profile = await session.scalar(
        sa.select(ProviderProfile)
        .where(ProviderProfile.user_id == user_id)
        .options(
            selectinload(ProviderProfile.user),
            selectinload(ProviderProfile.services).selectinload(ProviderService.service),
            selectinload(ProviderProfile.languages),
            selectinload(ProviderProfile.districts),
            selectinload(ProviderProfile.qualifications),
        )
    )
    if profile is None:
        raise NotFoundError("Профиль исполнителя не найден")
    return profile


def _detail(profile: ProviderProfile, is_favorite: bool = False) -> ProviderDetail:
    card = build_card(profile, is_favorite)
    return ProviderDetail(
        **card.model_dump(),
        about=profile.about,
        education=profile.education,
        video_key=profile.video_key,
        status=profile.status,
        work_radius_km=profile.work_radius_km,
        accepts_live_in=profile.accepts_live_in,
        has_car=profile.has_car,
        is_non_smoker=profile.is_non_smoker,
        documents_valid_until=profile.documents_valid_until,
        verification_level_updated_at=profile.verification_level_updated_at,
        services=[
            ProviderServiceOut(
                id=s.id,
                service_id=s.service_id,
                service_code=s.service.code if s.service else None,
                service_name=s.service.name_ru if s.service else None,
                price=s.price,
                price_unit=s.price_unit,
                min_duration_minutes=s.min_duration_minutes,
                is_active=s.is_active,
            )
            for s in profile.services
        ],
        qualification_ids=[q.qualification_id for q in profile.qualifications],
        district_ids=[d.district_id for d in profile.districts],
    )


# --- Кабинет исполнителя (важно объявить до "/{user_id}") ---


@router.post("/me", response_model=ProviderDetail, status_code=201, tags=["provider-cabinet"])
async def become_provider(user: CurrentUser, session: SessionDep) -> ProviderDetail:
    """Включает режим исполнителя у текущего аккаунта (совмещение ролей, п. 2 ТЗ)."""
    existing = await session.get(ProviderProfile, user.id)
    if existing is None:
        session.add(ProviderProfile(user_id=user.id, city_id=user.city_id))
        user.is_provider = True
        await session.flush()
    profile = await _load_profile(session, user.id)
    return _detail(profile)


@router.get("/me", response_model=ProviderDetail, tags=["provider-cabinet"])
async def my_profile(user: CurrentProvider, session: SessionDep) -> ProviderDetail:
    return _detail(await _load_profile(session, user.id))


@router.patch("/me", response_model=ProviderDetail, tags=["provider-cabinet"])
async def update_my_profile(
    data: ProviderProfileUpdateIn, user: CurrentProvider, session: SessionDep
) -> ProviderDetail:
    profile = await _load_profile(session, user.id)
    payload = data.model_dump(exclude_unset=True)

    district_ids = payload.pop("district_ids", None)
    qualification_ids = payload.pop("qualification_ids", None)
    languages = payload.pop("languages", None)

    for field_name, value in payload.items():
        setattr(profile, field_name, value)

    if district_ids is not None:
        profile.districts = [
            ProviderDistrict(provider_user_id=user.id, district_id=d) for d in district_ids
        ]
    if qualification_ids is not None:
        profile.qualifications = [
            ProviderQualification(provider_user_id=user.id, qualification_id=q)
            for q in qualification_ids
        ]
    if languages is not None:
        profile.languages = [
            ProviderLanguage(
                provider_user_id=user.id, language=item["language"], level=item["level"]
            )
            for item in languages
        ]

    await session.flush()
    return _detail(await _load_profile(session, user.id))


@router.put("/me/services", response_model=ProviderDetail, tags=["provider-cabinet"])
async def set_my_services(
    items: list[ProviderServiceIn], user: CurrentProvider, session: SessionDep
) -> ProviderDetail:
    """Полная замена прайс-листа исполнителя."""
    await session.execute(
        sa.delete(ProviderService).where(ProviderService.provider_user_id == user.id)
    )
    for item in items:
        session.add(ProviderService(provider_user_id=user.id, **item.model_dump()))
    await session.flush()
    return _detail(await _load_profile(session, user.id))


@router.post(
    "/me/verification",
    response_model=VerificationRequestOut,
    status_code=201,
    tags=["provider-cabinet"],
)
async def submit_verification(
    user: CurrentProvider,
    session: SessionDep,
    data: VerificationSubmitIn | None = None,
) -> VerificationRequestOut:
    """Подать анкету на проверку. Уровень 2 открывает анкету в поиске (п. 4.1 ТЗ)."""
    target = (data or VerificationSubmitIn()).target_level
    request = await moderation_service.submit_verification(session, user, target)
    return VerificationRequestOut.model_validate(request)


@router.get(
    "/me/verification",
    response_model=VerificationRequestOut | None,
    tags=["provider-cabinet"],
)
async def my_verification(
    user: CurrentProvider, session: SessionDep
) -> VerificationRequestOut | None:
    request = await moderation_service.my_verification_request(session, user)
    return VerificationRequestOut.model_validate(request) if request else None


# --- Календарь занятости (п. 5.2 ТЗ) ---


@router.get("/me/schedule", response_model=list[WeeklySlotOut], tags=["provider-cabinet"])
async def my_schedule(user: CurrentProvider, session: SessionDep) -> list[WeeklySlotOut]:
    rows = await session.scalars(
        sa.select(ProviderWeeklySlot)
        .where(ProviderWeeklySlot.provider_user_id == user.id)
        .order_by(ProviderWeeklySlot.weekday, ProviderWeeklySlot.time_from)
    )
    return [WeeklySlotOut.model_validate(s) for s in rows]


@router.put("/me/schedule", response_model=list[WeeklySlotOut], tags=["provider-cabinet"])
async def set_my_schedule(
    items: list[WeeklySlotIn], user: CurrentProvider, session: SessionDep
) -> list[WeeklySlotOut]:
    """Полная замена недельного расписания доступности."""
    for item in items:
        if item.time_to <= item.time_from:
            raise ConflictError("Время окончания должно быть позже начала")
    await session.execute(
        sa.delete(ProviderWeeklySlot).where(ProviderWeeklySlot.provider_user_id == user.id)
    )
    for item in items:
        session.add(ProviderWeeklySlot(provider_user_id=user.id, **item.model_dump()))
    await session.flush()
    rows = await session.scalars(
        sa.select(ProviderWeeklySlot)
        .where(ProviderWeeklySlot.provider_user_id == user.id)
        .order_by(ProviderWeeklySlot.weekday, ProviderWeeklySlot.time_from)
    )
    return [WeeklySlotOut.model_validate(s) for s in rows]


# --- Публичные карточки и избранное ---


# Объявлен до "/{user_id}": иначе путь /favorites уйдёт в него как UUID.
@router.get("/favorites", response_model=list[ProviderCard])
async def my_favorites(user: CurrentUser, session: SessionDep) -> list[ProviderCard]:
    """Сохранённые исполнители — основа повторного заказа в два клика (п. 5.1 ТЗ)."""
    favorite_ids = (
        await session.scalars(
            sa.select(Favorite.provider_user_id).where(Favorite.customer_id == user.id)
        )
    ).all()
    if not favorite_ids:
        return []
    profiles = (
        await session.scalars(
            sa.select(ProviderProfile)
            .where(ProviderProfile.user_id.in_(favorite_ids))
            .options(
                selectinload(ProviderProfile.user),
                selectinload(ProviderProfile.services),
                selectinload(ProviderProfile.languages),
            )
        )
    ).all()
    return [build_card(profile, is_favorite=True) for profile in profiles]


@router.get("/{user_id}", response_model=ProviderDetail)
async def get_provider(
    user_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> ProviderDetail:
    profile = await _load_profile(session, user_id)
    if profile.status != ProviderStatus.ACTIVE and user.id != user_id and not user.is_staff:
        raise NotFoundError("Профиль исполнителя не найден")
    is_favorite = (
        await session.get(Favorite, {"customer_id": user.id, "provider_user_id": user_id})
        is not None
    )
    return _detail(profile, is_favorite)


@router.put("/{user_id}/favorite", response_model=Ok)
async def add_favorite(user_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Ok:
    await _load_profile(session, user_id)
    exists = await session.get(Favorite, {"customer_id": user.id, "provider_user_id": user_id})
    if exists is None:
        session.add(Favorite(customer_id=user.id, provider_user_id=user_id))
    return Ok()


@router.delete("/{user_id}/favorite", response_model=Ok)
async def remove_favorite(user_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Ok:
    exists = await session.get(Favorite, {"customer_id": user.id, "provider_user_id": user_id})
    if exists is not None:
        await session.delete(exists)
    return Ok()
