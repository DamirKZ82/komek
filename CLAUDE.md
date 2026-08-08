# Komek — заметки для Claude Code

Маркетплейс услуг по уходу (няни, сиделки). ТЗ: `docs/tz-care-marketplace.md`.
Язык проекта — русский: комментарии, сообщения об ошибках API и коммиты пишем по-русски.

## Структура

- `backend/` — FastAPI + SQLAlchemy 2 async + PostgreSQL + Alembic. Venv: `backend/.venv` (Python 3.12).
- `mobile/` — Expo (React Native, TypeScript), UI — React Native Paper. Приоритет №1.
- `web/` — Next.js, ещё не начат.

## Команды (backend)

```powershell
cd D:\Projects\komek\backend
.\.venv\Scripts\python.exe -m pytest tests -q      # тесты (SQLite in-memory, БД не нужна)
.\.venv\Scripts\python.exe -m ruff check app tests  # линт
```

Миграции: alembic настроен на `settings.database_url`; для offline-операций
переопределяйте `DATABASE_URL` через переменную окружения (например `sqlite+aiosqlite://`).

## Конвенции backend

- Все datetime — aware UTC; при чтении из БД прогонять через `ensure_utc` перед арифметикой
  (SQLite в тестах теряет tzinfo).
- Статус заказа меняется только через `_transition()` в `app/services/orders.py` (карта переходов).
- Ошибки — подклассы `AppError` (`app/core/errors.py`), формат `{"error": {code, message}}`.
- Enum в БД — строки (native_enum=False), значения не переименовывать.
- Локализация справочников: колонки `name_ru`/`name_kk`, наружу отдаётся уже выбранный текст.
- Не добавлять элементы в lazy-коллекции загруженных объектов в async-коде — MissingGreenlet;
  добавлять записи через `session.add()`.

## Ограничения окружения

- Windows, Docker и PostgreSQL не установлены — проверка схемы и тесты идут через SQLite
  (aiosqlite). docker-compose.yml лежит в корне на будущее.
- Телефоны в тестах должны проходить валидацию `phonenumbers` для KZ
  (префиксы 701/702/705/707/708/747 валидны, 703/704 — нет).
