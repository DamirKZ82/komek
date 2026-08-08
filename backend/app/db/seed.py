"""Сид справочников MVP: услуги, квалификации, Астана с районами.

Запуск: python -m app.db.seed
Идемпотентен — существующие записи (по code) не трогает.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.cancellation import CancellationRule
from app.models.catalog import Qualification, Service, ServiceCategory
from app.models.enums import MonetizationType, PriceUnit, Vertical
from app.models.geo import City, District

# Тип A (fee за подбор): долгосрочные постоянные исполнители (п. 5.8 ТЗ).
# Остальные услуги — комиссия с заказа (типы B/C).
PLACEMENT_FEE_SERVICES = {"nanny_fulltime"}

CATEGORIES = [
    # (code, vertical, name_ru, name_kk, icon, services)
    (
        "children",
        Vertical.CHILDREN,
        "Дети",
        "Балалар",
        "child_care",
        [
            # (code, name_ru, name_kk, units, min_minutes, urgent, is_mvp, req_rank)
            ("babysitter_hourly", "Бебиситтер почасово", "Сағаттық бебиситтер",
             [PriceUnit.HOUR], 120, True, True, 2),
            ("nanny_fulltime", "Няня постоянная", "Тұрақты күтуші",
             [PriceUnit.SHIFT, PriceUnit.MONTH], 480, False, True, 2),
            ("night_nanny", "Ночная няня", "Түнгі күтуші",
             [PriceUnit.SHIFT], 480, False, False, 2),
            ("child_escort", "Сопровождение ребёнка", "Баланы алып жүру",
             [PriceUnit.HOUR], 60, True, False, 2),
            ("special_needs_nanny", "Няня для ребёнка с особыми потребностями",
             "Ерекше қажеттіліктері бар балаға күтуші", [PriceUnit.HOUR], 120, False, False, 2),
        ],
    ),
    (
        "elderly",
        Vertical.ELDERLY,
        "Пожилые",
        "Қарттар",
        "elderly",
        [
            ("caregiver_hourly", "Сиделка почасовая", "Сағаттық күтуші",
             [PriceUnit.HOUR], 120, True, True, 2),
            ("caregiver_shift", "Сиделка посменно", "Ауысымдық күтуші",
             [PriceUnit.SHIFT], 480, False, True, 2),
            ("post_discharge_care", "Уход после выписки", "Шыққаннан кейінгі күтім",
             [PriceUnit.SHIFT, PriceUnit.HOUR], 240, True, False, 2),
            ("dementia_care", "Уход при деменции", "Деменция кезіндегі күтім",
             [PriceUnit.HOUR, PriceUnit.SHIFT], 240, False, False, 2),
            ("companion", "Компаньон для пожилых", "Қарттарға серік",
             [PriceUnit.HOUR], 120, True, True, 1),
        ],
    ),
]

QUALIFICATIONS = [
    # (code, vertical|None, name_ru, name_kk, requires_document)
    ("newborn_experience", Vertical.CHILDREN,
     "Опыт с новорождёнными", "Нәрестелермен тәжірибе", False),
    ("autism_experience", Vertical.CHILDREN,
     "Опыт с детьми с РАС", "РАС бар балалармен тәжірибе", False),
    ("cerebral_palsy_experience", Vertical.CHILDREN,
     "Опыт с детьми с ДЦП", "БЦС бар балалармен тәжірибе", False),
    ("pedagogical_education", Vertical.CHILDREN,
     "Педагогическое образование", "Педагогикалық білім", True),
    ("dementia_experience", Vertical.ELDERLY,
     "Опыт ухода при деменции", "Деменция кезінде күтім тәжірибесі", False),
    ("bedridden_care", Vertical.ELDERLY,
     "Уход за лежачими", "Төсек тартқандарға күтім", False),
    ("medical_education", Vertical.ELDERLY,
     "Медицинское образование", "Медициналық білім", True),
    ("first_aid", None, "Сертификат первой помощи", "Алғашқы көмек сертификаты", True),
]

# Районы Астаны.
ASTANA_DISTRICTS = [
    ("almaty_district", "Алматы", "Алматы ауданы"),
    ("baikonyr", "Байконыр", "Байқоңыр ауданы"),
    ("yesil", "Есиль", "Есіл ауданы"),
    ("nura", "Нура", "Нұра ауданы"),
    ("saryarka", "Сарыарка", "Сарыарқа ауданы"),
]


async def seed(session: AsyncSession) -> None:
    # Город запуска: Астана (этап 1). Алматы добавлена неактивной для этапа 2.
    for code, name_ru, name_kk, lat, lon, active, order in [
        ("astana", "Астана", "Астана", 51.1282, 71.4307, True, 0),
        ("almaty", "Алматы", "Алматы", 43.2380, 76.9452, False, 1),
    ]:
        city = await session.scalar(sa.select(City).where(City.code == code))
        if city is None:
            city = City(
                code=code, name_ru=name_ru, name_kk=name_kk,
                latitude=lat, longitude=lon, is_active=active, sort_order=order,
            )
            session.add(city)
            await session.flush()
        if code == "astana":
            for d_code, d_ru, d_kk in ASTANA_DISTRICTS:
                exists = await session.scalar(
                    sa.select(District).where(
                        District.city_id == city.id, District.code == d_code
                    )
                )
                if exists is None:
                    session.add(
                        District(city_id=city.id, code=d_code, name_ru=d_ru, name_kk=d_kk)
                    )

    for idx, (code, vertical, name_ru, name_kk, icon, services) in enumerate(CATEGORIES):
        category = await session.scalar(
            sa.select(ServiceCategory).where(ServiceCategory.code == code)
        )
        if category is None:
            category = ServiceCategory(
                code=code, vertical=vertical, name_ru=name_ru, name_kk=name_kk,
                icon=icon, sort_order=idx,
            )
            session.add(category)
            await session.flush()
        for s_idx, (s_code, s_ru, s_kk, units, min_min, urgent, is_mvp, rank) in enumerate(
            services
        ):
            exists = await session.scalar(sa.select(Service).where(Service.code == s_code))
            if exists is None:
                session.add(
                    Service(
                        category_id=category.id,
                        code=s_code,
                        name_ru=s_ru,
                        name_kk=s_kk,
                        allowed_price_units=[u.value for u in units],
                        min_duration_minutes=min_min,
                        supports_urgent=urgent,
                        is_mvp=is_mvp,
                        is_active=is_mvp,  # не-MVP услуги заведены, но выключены
                        required_verification_rank=rank,
                        monetization_type=(
                            MonetizationType.PLACEMENT_FEE
                            if s_code in PLACEMENT_FEE_SERVICES
                            else MonetizationType.COMMISSION
                        ),
                        sort_order=s_idx,
                    )
                )

    # Дефолтные правила отмены (п. 5.3 ТЗ): меньше 4ч — 50%, меньше 24ч — 20%.
    for hours, percent in [(4, Decimal("50")), (24, Decimal("20"))]:
        exists = await session.scalar(
            sa.select(CancellationRule).where(CancellationRule.hours_before == hours)
        )
        if exists is None:
            session.add(CancellationRule(hours_before=hours, penalty_percent=percent))

    for idx, (code, vertical, name_ru, name_kk, requires_doc) in enumerate(QUALIFICATIONS):
        exists = await session.scalar(
            sa.select(Qualification).where(Qualification.code == code)
        )
        if exists is None:
            session.add(
                Qualification(
                    code=code, vertical=vertical, name_ru=name_ru, name_kk=name_kk,
                    requires_document=requires_doc, sort_order=idx,
                )
            )


async def main() -> None:
    async with async_session_factory() as session:
        await seed(session)
        await session.commit()
    print("Справочники засеяны.")


if __name__ == "__main__":
    asyncio.run(main())
