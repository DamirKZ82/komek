"""Перечисления доменной модели. Значения хранятся в БД строками — не переименовывать."""

from __future__ import annotations

from enum import StrEnum


class Locale(StrEnum):
    RU = "ru"
    KK = "kk"


class Language(StrEnum):
    """Языки, которыми владеет исполнитель (п. 5.1 ТЗ)."""

    RU = "ru"
    KK = "kk"
    EN = "en"
    TR = "tr"


class LanguageLevel(StrEnum):
    BASIC = "basic"
    CONVERSATIONAL = "conversational"
    NATIVE = "native"


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"  # временная блокировка, в т.ч. автоматическая по жалобе
    DELETED = "deleted"  # мягкое удаление, право на удаление ПДн


class StaffRole(StrEnum):
    MODERATOR = "moderator"
    ADMIN = "admin"


class Gender(StrEnum):
    FEMALE = "female"
    MALE = "male"


class ConsentType(StrEnum):
    """Согласия по Закону РК «О персональных данных» (п. 6 ТЗ)."""

    PERSONAL_DATA = "personal_data"
    PUBLIC_OFFER = "public_offer"
    BACKGROUND_CHECK = "background_check"  # согласие на проверку справок
    GEO_TRACKING = "geo_tracking"  # чек-ин/чек-аут и сопровождение ребёнка
    MARKETING = "marketing"


class OtpPurpose(StrEnum):
    LOGIN = "login"
    PHONE_CHANGE = "phone_change"


class Vertical(StrEnum):
    CHILDREN = "children"
    ELDERLY = "elderly"
    DISABILITY = "disability"
    PETS = "pets"


class PriceUnit(StrEnum):
    HOUR = "hour"
    SHIFT = "shift"
    DAY = "day"
    MONTH = "month"


class MonetizationType(StrEnum):
    """Способ заработка привязан к типу заказа (п. 5.8 ТЗ)."""

    COMMISSION = "commission"  # типы B/C: комиссия 15% с каждого заказа
    PLACEMENT_FEE = "placement_fee"  # тип A: разовый fee за успешный подбор


class PlacementFeeStatus(StrEnum):
    PENDING = "pending"  # ожидает оплаты заказчиком
    PAID = "paid"
    WAIVED = "waived"  # бесплатный повторный подбор по гарантии замены


class VerificationLevel(StrEnum):
    """Публичный уровень доверия к анкете (п. 4.1 ТЗ)."""

    REGISTERED = "level_0"
    IDENTITY = "level_1"
    VERIFIED = "level_2"
    PROFESSIONAL = "level_3"

    @property
    def rank(self) -> int:
        return int(self.value.removeprefix("level_"))


class ProviderStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    PAUSED = "paused"  # исполнитель сам скрыл анкету
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class DocumentType(StrEnum):
    ID_CARD = "id_card"
    SELFIE = "selfie"  # liveness-проверка, fallback к Digital ID
    CRIMINAL_RECORD = "criminal_record"  # справка об отсутствии судимости
    PSYCH_DISPENSARY = "psych_dispensary"
    NARCO_DISPENSARY = "narco_dispensary"
    MEDICAL_BOOK = "medical_book"
    EDUCATION = "education"
    CERTIFICATE = "certificate"  # первая помощь и т.п.


class DocumentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class VerificationRequestStatus(StrEnum):
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    NEEDS_FIX = "needs_fix"
    APPROVED = "approved"
    REJECTED = "rejected"


class InterviewType(StrEnum):
    VIDEO_CALL = "video_call"
    RECORDED = "recorded"


class OrderSource(StrEnum):
    CATALOG = "catalog"  # заказчик выбрал исполнителя сам
    REQUEST = "request"  # заказчик опубликовал заявку, исполнители откликаются


class OrderStatus(StrEnum):
    """Жизненный цикл заказа, п. 5.3 ТЗ."""

    DRAFT = "draft"
    PUBLISHED = "published"  # заявка видна исполнителям
    SENT = "sent"  # предложение отправлено конкретному исполнителю
    ACCEPTED = "accepted"  # исполнитель согласился
    CONFIRMED = "confirmed"  # средства захолдированы
    IN_PROGRESS = "in_progress"  # чек-ин выполнен
    COMPLETED = "completed"  # чек-аут выполнен
    PAID = "paid"  # списание прошло, выплата поставлена в реестр
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # никто не откликнулся до начала


class CancelledBy(StrEnum):
    CUSTOMER = "customer"
    PROVIDER = "provider"
    PLATFORM = "platform"


class OrderResponseStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    SYSTEM = "system"


class PaymentProvider(StrEnum):
    KASPI = "kaspi"
    CARD = "card"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    HELD = "held"  # холд средств при подтверждении заказа
    CAPTURED = "captured"  # списание после чек-аута
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PayoutStatus(StrEnum):
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"


class PayoutMethod(StrEnum):
    KASPI = "kaspi"
    CARD = "card"


class ReviewDirection(StrEnum):
    CUSTOMER_TO_PROVIDER = "customer_to_provider"
    PROVIDER_TO_CUSTOMER = "provider_to_customer"


class ReviewStatus(StrEnum):
    PENDING = "pending"  # в ручной очереди модерации (оценки 1–2, стоп-слова)
    PUBLISHED = "published"
    REJECTED = "rejected"


class ComplaintCategory(StrEnum):
    SAFETY = "safety"  # автоматическая приостановка профиля до разбора
    FRAUD = "fraud"
    QUALITY = "quality"
    NO_SHOW = "no_show"
    OFF_PLATFORM = "off_platform"  # попытка увести сделку мимо платформы
    SPAM = "spam"
    OTHER = "other"


class ComplaintStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class SmsStatus(StrEnum):
    """Жизненный цикл SMS у провайдера."""

    QUEUED = "queued"  # принято нами, ещё не отправлено
    SENT = "sent"  # передано провайдеру
    DELIVERED = "delivered"  # подтверждена доставка на телефон
    FAILED = "failed"  # провайдер отклонил или не доставил
    EXPIRED = "expired"  # срок доставки истёк


class KycSessionStatus(StrEnum):
    """Сессия проверки личности у KYC-провайдера (п. 4.2 шаг 3 ТЗ)."""

    CREATED = "created"  # ждём прохождения в мобильном SDK
    PENDING = "pending"  # пользователь прошёл, провайдер обрабатывает
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"


class DevicePlatform(StrEnum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"
