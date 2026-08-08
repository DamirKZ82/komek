"""Гео-справочники и адреса. Координаты — обычные float; PostGIS в MVP не нужен."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity


class City(Entity):
    __tablename__ = "cities"

    code: Mapped[str] = mapped_column(sa.String(32), unique=True)
    name_ru: Mapped[str] = mapped_column(sa.String(120))
    name_kk: Mapped[str] = mapped_column(sa.String(120))
    latitude: Mapped[float] = mapped_column(sa.Float)
    longitude: Mapped[float] = mapped_column(sa.Float)
    timezone: Mapped[str] = mapped_column(sa.String(64), default="Asia/Almaty")
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0)

    districts: Mapped[list[District]] = relationship(back_populates="city")


class District(Entity):
    __tablename__ = "districts"
    __table_args__ = (sa.UniqueConstraint("city_id", "code", name="uq_districts_city_code"),)

    city_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cities.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(sa.String(48))
    name_ru: Mapped[str] = mapped_column(sa.String(120))
    name_kk: Mapped[str] = mapped_column(sa.String(120))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)

    city: Mapped[City] = relationship(back_populates="districts")


class Address(Entity):
    """Адрес заказчика. В заказе дублируется снимком, чтобы правки не меняли историю."""

    __tablename__ = "addresses"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    city_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("cities.id"), nullable=True)
    district_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("districts.id"), nullable=True
    )
    label: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)  # «дом», «дача мамы»
    street: Mapped[str] = mapped_column(sa.String(255))
    building: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    apartment: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    entrance: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    intercom: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    city: Mapped[City | None] = relationship()
    district: Mapped[District | None] = relationship()

    def as_snapshot(self) -> dict[str, object]:
        return {
            "street": self.street,
            "building": self.building,
            "apartment": self.apartment,
            "entrance": self.entrance,
            "comment": self.comment,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }
