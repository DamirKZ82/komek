"""Конфигурация приложения. Все значения переопределяются через .env или переменные окружения."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень backend-пакета: .env ищем рядом с pyproject.toml, а не в cwd процесса.
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Приложение ---
    app_name: str = "Komek API"
    environment: str = "local"  # local | staging | production
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    # Через запятую: "https://a.kz,https://b.kz" или "*".
    cors_origins: str = "*"

    # --- База данных ---
    database_url: str = "postgresql+asyncpg://komek:komek@localhost:5432/komek"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- Аутентификация ---
    jwt_secret: str = "dev-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 60

    # --- Одноразовые коды (SMS) ---
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    # В local/staging SMS не отправляется, а код фиксирован — чтобы можно было тестировать вход.
    otp_debug_code: str | None = "111111"

    # --- Бизнес-правила ---
    default_currency: str = "KZT"
    default_city_code: str = "astana"
    # Гибридная монетизация (п. 5.8 ТЗ):
    # типы B/C — комиссия 15% с исполнителя при выплате;
    # тип A (подбор постоянного исполнителя) — разовый fee с заказчика, без комиссии.
    default_commission_rate: Decimal = Decimal("0.15")
    # Fee за подбор: доля месячной ставки исполнителя (ориентир 30–50% по ТЗ).
    placement_fee_rate: Decimal = Decimal("0.40")
    # Гарантия замены: бесплатный повторный подбор в течение этого срока.
    placement_guarantee_days: int = 30
    # Минимальный уровень верификации, при котором анкета попадает в поиск (п. 4.1 ТЗ).
    min_searchable_verification_level: int = 2
    # Сроки действия справок — внутренние нормативы платформы (п. 4.2 ТЗ).
    criminal_record_validity_days: int = 90  # несудимость: 3 месяца
    dispensary_validity_days: int = 180  # психо-/наркодиспансер: 6 месяцев
    # Напоминания «обновите справку» за N дней до истечения.
    document_expiry_reminder_days: tuple[int, ...] = (14, 3)
    review_window_days: int = 14
    review_edit_window_hours: int = 48
    # Заказ считается срочным, если до начала меньше этого времени.
    urgent_order_threshold_hours: int = 12

    # --- Платёжный шлюз: Kaspi Pay / эквайринг банка (п. 5.5 ТЗ) ---
    # Пусто → sandbox-режим (запрещён в production).
    payment_api_url: str | None = None
    payment_api_key: str | None = None
    # Секрет для проверки HMAC-подписи вебхуков эквайера.
    payment_webhook_secret: str | None = None
    # Куда эквайер шлёт callback: https://api.komek.kz/api/v1/webhooks/payments
    payment_webhook_url: str | None = None
    # Допустимый возраст вебхука в секундах — защита от replay-атак.
    payment_webhook_max_age_seconds: int = 300

    # --- KYC-провайдер: liveness + распознавание удостоверения (п. 4.2 ТЗ) ---
    # Пусто → заглушка, которая принимает любую сессию (только вне production).
    kyc_api_url: str | None = None
    kyc_api_key: str | None = None
    # Минимальный возраст исполнителя (п. 4.1 ТЗ: уровень 1 — 18+).
    min_provider_age: int = 18

    # --- SMS-шлюз (п. 5.4 ТЗ) ---
    # Пусто → сообщения только в лог (local/staging).
    sms_api_url: str | None = None
    sms_api_key: str | None = None
    sms_sender: str = "Komek"

    # --- Хранилище документов (S3-совместимое, отдельный шифруемый бакет) ---
    s3_endpoint_url: str | None = None
    s3_region: str = "kz-ast-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_media_bucket: str = "komek-media"
    s3_documents_bucket: str = "komek-documents"

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
