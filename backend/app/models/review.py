"""Двусторонние отзывы (п. 5.6 ТЗ). Отзыв возможен только по оплаченному заказу."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, enum_column
from app.models.enums import ReviewDirection, ReviewStatus


class Review(Entity):
    __tablename__ = "reviews"
    __table_args__ = (
        # По одному отзыву от каждой стороны на заказ.
        sa.UniqueConstraint("order_id", "direction", name="uq_reviews_order_direction"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        sa.Index("ix_reviews_target_status", "target_id", "status"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    target_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    direction: Mapped[ReviewDirection] = mapped_column(
        enum_column(ReviewDirection, "review_direction")
    )

    rating: Mapped[int] = mapped_column(sa.SmallInteger)
    # Разбивка по критериям — только для отзывов на исполнителя.
    rating_punctuality: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    rating_attitude: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    rating_communication: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    status: Mapped[ReviewStatus] = mapped_column(
        enum_column(ReviewStatus, "review_status"), default=ReviewStatus.PENDING, index=True
    )
    moderation_notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    editable_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # Ответ второй стороны на отзыв.
    reply_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    reply_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
