"""Нормализация телефонов: на вход что угодно, в БД — только E.164."""

from __future__ import annotations

import phonenumbers

from app.core.errors import AppError


class InvalidPhoneError(AppError):
    code = "invalid_phone"
    message = "Некорректный номер телефона"


def normalize_phone(raw: str, default_region: str = "KZ") -> str:
    try:
        parsed = phonenumbers.parse(raw.strip(), default_region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhoneError() from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneError()
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
