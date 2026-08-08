"""Каталог услуг и квалификаций (раздел 3 ТЗ)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, enum_column
from app.models.enums import MonetizationType, PriceUnit, Vertical


class ServiceCategory(Entity):
    __tablename__ = "service_categories"

    code: Mapped[str] = mapped_column(sa.String(64), unique=True)
    vertical: Mapped[Vertical] = mapped_column(enum_column(Vertical, "vertical"), index=True)
    name_ru: Mapped[str] = mapped_column(sa.String(160))
    name_kk: Mapped[str] = mapped_column(sa.String(160))
    icon: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)

    services: Mapped[list[Service]] = relationship(back_populates="category")


class Service(Entity):
    """Конкретная услуга внутри категории: бебиситтер почасово, сиделка и т.д."""

    __tablename__ = "services"

    category_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("service_categories.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(sa.String(64), unique=True)
    name_ru: Mapped[str] = mapped_column(sa.String(160))
    name_kk: Mapped[str] = mapped_column(sa.String(160))
    description_ru: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    description_kk: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # Какие единицы тарификации допустимы для услуги: ["hour", "shift"].
    allowed_price_units: Mapped[list[str]] = mapped_column(
        sa.JSON, default=lambda: [PriceUnit.HOUR.value]
    )
    # Минимальный уровень верификации исполнителя для доступа к услуге (п. 4.1 ТЗ).
    required_verification_rank: Mapped[int] = mapped_column(sa.Integer, default=2)
    # Тип A (fee за подбор) или B/C (комиссия с заказа) — п. 5.8 ТЗ.
    monetization_type: Mapped[MonetizationType] = mapped_column(
        enum_column(MonetizationType, "monetization_type"),
        default=MonetizationType.COMMISSION,
    )
    min_duration_minutes: Mapped[int] = mapped_column(sa.Integer, default=120)
    supports_urgent: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    is_mvp: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0)

    category: Mapped[ServiceCategory] = relationship(back_populates="services")


class Qualification(Entity):
    """Специальные навыки-фильтры: опыт с РАС, ДЦП, деменцией, новорождёнными, первая помощь."""

    __tablename__ = "qualifications"

    code: Mapped[str] = mapped_column(sa.String(64), unique=True)
    vertical: Mapped[Vertical | None] = mapped_column(
        enum_column(Vertical, "qualification_vertical"), nullable=True
    )
    name_ru: Mapped[str] = mapped_column(sa.String(160))
    name_kk: Mapped[str] = mapped_column(sa.String(160))
    # Требует документального подтверждения (диплом/сертификат), иначе — самодекларация.
    requires_document: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
