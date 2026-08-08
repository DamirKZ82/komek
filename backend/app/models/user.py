"""Пользователи, согласия, устройства и одноразовые коды."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, enum_column
from app.models.enums import (
    ConsentType,
    DevicePlatform,
    Gender,
    Locale,
    OtpPurpose,
    StaffRole,
    UserStatus,
)


class User(Entity):
    """Один аккаунт может быть одновременно заказчиком и исполнителем (п. 2 ТЗ)."""

    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(sa.String(20), unique=True, index=True)  # E.164
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    email: Mapped[str | None] = mapped_column(sa.String(255), unique=True, nullable=True)

    first_name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    patronymic: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    gender: Mapped[Gender | None] = mapped_column(enum_column(Gender, "gender"), nullable=True)
    avatar_key: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)

    # ИИН — чувствительные ПДн: колонка заполняется только после верификации личности
    # и должна шифроваться на уровне приложения (см. docs/security.md).
    iin_encrypted: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    identity_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    locale: Mapped[Locale] = mapped_column(enum_column(Locale, "locale"), default=Locale.RU)
    city_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("cities.id"), nullable=True)

    is_customer: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    is_provider: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    staff_role: Mapped[StaffRole | None] = mapped_column(
        enum_column(StaffRole, "staff_role"), nullable=True
    )

    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus, "user_status"), default=UserStatus.ACTIVE, index=True
    )
    suspended_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    provider_profile: Mapped[ProviderProfile | None] = relationship(  # noqa: F821
        "ProviderProfile", back_populates="user", uselist=False
    )
    consents: Mapped[list[UserConsent]] = relationship(back_populates="user")
    devices: Mapped[list[Device]] = relationship(back_populates="user")

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.last_name, self.first_name) if part)

    @property
    def is_staff(self) -> bool:
        return self.staff_role is not None

    @property
    def is_identity_verified(self) -> bool:
        return self.identity_verified_at is not None


class UserConsent(Entity):
    """Журнал согласий: что, когда, какой версии документа и с какого IP."""

    __tablename__ = "user_consents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    consent_type: Mapped[ConsentType] = mapped_column(enum_column(ConsentType, "consent_type"))
    document_version: Mapped[str] = mapped_column(sa.String(32))
    granted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)

    user: Mapped[User] = relationship(back_populates="consents")


class Device(Entity):
    """Push-токены (FCM/APNS) для уведомлений, п. 5.4 ТЗ."""

    __tablename__ = "devices"
    __table_args__ = (sa.UniqueConstraint("push_token", name="uq_devices_push_token"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[DevicePlatform] = mapped_column(enum_column(DevicePlatform, "device_platform"))
    push_token: Mapped[str] = mapped_column(sa.String(512))
    app_version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    locale: Mapped[Locale | None] = mapped_column(
        enum_column(Locale, "device_locale"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="devices")


class OtpCode(Entity):
    """Одноразовый код входа. Хранится только HMAC — см. core.security."""

    __tablename__ = "otp_codes"

    phone: Mapped[str] = mapped_column(sa.String(20), index=True)
    purpose: Mapped[OtpPurpose] = mapped_column(
        enum_column(OtpPurpose, "otp_purpose"), default=OtpPurpose.LOGIN
    )
    code_hash: Mapped[str] = mapped_column(sa.String(128))
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
