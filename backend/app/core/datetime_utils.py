"""Работа с датами: в домене все datetime — aware UTC.

SQLite (тесты) теряет tzinfo при чтении; ensure_utc делает значение снова aware.
Для PostgreSQL с timestamptz это no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
