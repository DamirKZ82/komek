"""Назначение staff-роли пользователю (бутстрап модераторов).

Запуск: python -m app.db.make_staff +77011234567 [moderator|admin]
Пользователь должен хотя бы раз войти в приложение (создать аккаунт).
"""

from __future__ import annotations

import asyncio
import sys

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models.enums import StaffRole
from app.models.user import User
from app.services.phone import normalize_phone


async def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python -m app.db.make_staff <телефон> [moderator|admin]")
        raise SystemExit(1)
    phone = normalize_phone(sys.argv[1])
    role = StaffRole(sys.argv[2]) if len(sys.argv) > 2 else StaffRole.MODERATOR

    async with async_session_factory() as session:
        user = await session.scalar(sa.select(User).where(User.phone == phone))
        if user is None:
            print(f"Пользователь {phone} не найден — сначала войдите в приложение этим номером.")
            raise SystemExit(1)
        user.staff_role = role
        await session.commit()
        print(f"{phone} теперь {role.value}.")


if __name__ == "__main__":
    asyncio.run(main())
