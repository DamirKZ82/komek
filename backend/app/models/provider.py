"""Профиль исполнителя, его услуги, зоны работы и календарь (п. 5.2 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Entity, TimestampMixin, enum_column
from app.models.enums import (
    Language,
    LanguageLevel,
    PriceUnit,
    ProviderStatus,
    VerificationLevel,
)


class ProviderProfile(Base, TimestampMixin):
    """Ключ — user_id: профиль исполнителя это «вторая сторона» того же аккаунта."""

    __tablename__ = "provider_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    headline: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    about: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    video_key: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    experience_years: Mapped[int] = mapped_column(sa.Integer, default=0)
    education: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    status: Mapped[ProviderStatus] = mapped_column(
        enum_column(ProviderStatus, "provider_status"), default=ProviderStatus.DRAFT, index=True
    )
    verification_level: Mapped[VerificationLevel] = mapped_column(
        enum_column(VerificationLevel, "verification_level"),
        default=VerificationLevel.REGISTERED,
        index=True,
    )
    verification_level_updated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # Ближайшая дата протухания справок — по ней воркер шлёт напоминания (п. 4.2 ТЗ).
    documents_valid_until: Mapped[date | None] = mapped_column(sa.Date, nullable=True)

    # Зона работы
    city_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("cities.id"), nullable=True)
    base_latitude: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    base_longitude: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    work_radius_km: Mapped[int] = mapped_column(sa.Integer, default=10)

    accepts_urgent: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    accepts_live_in: Mapped[bool] = mapped_column(sa.Boolean, default=False)  # с проживанием
    has_car: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    is_non_smoker: Mapped[bool] = mapped_column(sa.Boolean, default=True)

    # Денормализованные показатели: пересчитываются при публикации отзыва / оплате заказа.
    rating_avg: Mapped[Decimal | None] = mapped_column(sa.Numeric(3, 2), nullable=True)
    rating_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    completed_orders_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    response_time_minutes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="provider_profile")  # noqa: F821
    services: Mapped[list[ProviderService]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )
    languages: Mapped[list[ProviderLanguage]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )
    districts: Mapped[list[ProviderDistrict]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )
    qualifications: Mapped[list[ProviderQualification]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )

    @property
    def is_searchable(self) -> bool:
        return self.status == ProviderStatus.ACTIVE


class ProviderService(Entity):
    __tablename__ = "provider_services"
    __table_args__ = (
        sa.UniqueConstraint(
            "provider_user_id", "service_id", "price_unit", name="uq_provider_services_offer"
        ),
        sa.CheckConstraint("price > 0", name="price_positive"),
    )

    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("services.id", ondelete="RESTRICT"), index=True
    )
    price: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    price_unit: Mapped[PriceUnit] = mapped_column(enum_column(PriceUnit, "price_unit"))
    min_duration_minutes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)

    provider: Mapped[ProviderProfile] = relationship(back_populates="services")
    service: Mapped[Service] = relationship()  # noqa: F821


class ProviderLanguage(Base, TimestampMixin):
    __tablename__ = "provider_languages"

    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[Language] = mapped_column(
        enum_column(Language, "provider_language"), primary_key=True
    )
    level: Mapped[LanguageLevel] = mapped_column(
        enum_column(LanguageLevel, "language_level"), default=LanguageLevel.CONVERSATIONAL
    )

    provider: Mapped[ProviderProfile] = relationship(back_populates="languages")


class ProviderDistrict(Base, TimestampMixin):
    """Районы, куда исполнитель готов выезжать."""

    __tablename__ = "provider_districts"

    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), primary_key=True
    )
    district_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("districts.id", ondelete="CASCADE"), primary_key=True
    )

    provider: Mapped[ProviderProfile] = relationship(back_populates="districts")
    district: Mapped[District] = relationship()  # noqa: F821


class ProviderQualification(Base, TimestampMixin):
    __tablename__ = "provider_qualifications"

    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), primary_key=True
    )
    qualification_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("qualifications.id", ondelete="CASCADE"), primary_key=True
    )
    # Подтверждена документом и проверена модератором, иначе — слова исполнителя.
    is_verified: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("verification_documents.id", ondelete="SET NULL"), nullable=True
    )

    provider: Mapped[ProviderProfile] = relationship(back_populates="qualifications")
    qualification: Mapped[Qualification] = relationship()  # noqa: F821


class ProviderWeeklySlot(Entity):
    """Регулярная доступность: «пн 09:00–18:00». Основа календаря занятости."""

    __tablename__ = "provider_weekly_slots"
    __table_args__ = (sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),)

    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(sa.SmallInteger)  # 0 = понедельник
    time_from: Mapped[time] = mapped_column(sa.Time)
    time_to: Mapped[time] = mapped_column(sa.Time)


class ProviderDateException(Entity):
    """Точечное отклонение от расписания: отпуск или, наоборот, дополнительная смена."""

    __tablename__ = "provider_date_exceptions"
    __table_args__ = (
        sa.UniqueConstraint("provider_user_id", "date", name="uq_provider_date_exceptions_date"),
    )

    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(sa.Date)
    is_available: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    time_from: Mapped[time | None] = mapped_column(sa.Time, nullable=True)
    time_to: Mapped[time | None] = mapped_column(sa.Time, nullable=True)
    comment: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)


class Favorite(Base, TimestampMixin):
    """«Избранные» исполнители заказчика — повторный заказ в два клика (п. 5.1 ТЗ)."""

    __tablename__ = "favorites"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider_user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("provider_profiles.user_id", ondelete="CASCADE"), primary_key=True
    )
