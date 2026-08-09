"""Все модели импортируются здесь: alembic и SQLAlchemy видят полную метадату."""

from app.db.base import Base
from app.models.cancellation import CancellationRule
from app.models.catalog import Qualification, Service, ServiceCategory
from app.models.chat import ChatMessage, ChatThread
from app.models.geo import Address, City, District
from app.models.moderation import AuditLog, Complaint
from app.models.order import (
    Order,
    OrderRecurrence,
    OrderResponse,
    OrderStatusHistory,
)
from app.models.payment import (
    CommissionRule,
    Payment,
    Payout,
    PayoutItem,
    PromoCode,
)
from app.models.placement import Placement
from app.models.provider import (
    Favorite,
    ProviderDateException,
    ProviderDistrict,
    ProviderLanguage,
    ProviderProfile,
    ProviderQualification,
    ProviderService,
    ProviderWeeklySlot,
)
from app.models.review import Review
from app.models.user import Device, OtpCode, User, UserConsent
from app.models.verification import (
    DocumentAccessLog,
    VerificationDocument,
    VerificationInterview,
    VerificationRequest,
)
from app.models.webhook import WebhookEvent

__all__ = [
    "Address",
    "AuditLog",
    "Base",
    "CancellationRule",
    "ChatMessage",
    "ChatThread",
    "City",
    "CommissionRule",
    "Complaint",
    "Device",
    "District",
    "DocumentAccessLog",
    "Favorite",
    "Order",
    "OrderRecurrence",
    "OrderResponse",
    "OrderStatusHistory",
    "OtpCode",
    "Payment",
    "Payout",
    "PayoutItem",
    "Placement",
    "PromoCode",
    "ProviderDateException",
    "ProviderDistrict",
    "ProviderLanguage",
    "ProviderProfile",
    "ProviderQualification",
    "ProviderService",
    "ProviderWeeklySlot",
    "Qualification",
    "Review",
    "Service",
    "ServiceCategory",
    "User",
    "UserConsent",
    "VerificationDocument",
    "VerificationInterview",
    "VerificationRequest",
    "WebhookEvent",
]
