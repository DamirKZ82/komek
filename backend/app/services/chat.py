"""Чат с антидизинтермедиацией (п. 5.4 ТЗ).

Пока между парой нет оплаченного через платформу заказа, контакты в сообщениях
маскируются: телефоны, e-mail, ссылки на мессенджеры и @-ники. Исходный текст
сохраняется в raw_body и доступен только модератору при разборе жалобы.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.models.chat import ChatMessage, ChatThread
from app.models.enums import MessageType, OrderStatus
from app.models.order import Order
from app.models.provider import ProviderProfile
from app.models.user import User
from app.services.notifications import notify_user

MASK = "•••"

# Порядок важен: сначала ссылки/адреса, затем «голые» номера.
_CONTACT_PATTERNS = [
    # Ссылки на мессенджеры и соцсети
    re.compile(r"(?:https?://)?(?:wa\.me|t\.me|telegram\.me|instagram\.com|vk\.com)/\S+", re.I),
    re.compile(r"\b(?:whatsapp|ватсап|вотсап|telegram|телеграм|инстаграм)\b[\s:]*@?\S*", re.I),
    # E-mail
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    # Телефоны: +7..., 8707..., с пробелами/скобками/дефисами (минимум 10 цифр всего)
    re.compile(r"(?<!\d)(?:\+?\d[\s\-().]*){10,15}(?!\d)"),
    # @-ники
    re.compile(r"(?<!\w)@[a-zA-Z_]\w{2,}"),
]


def mask_contacts(text: str) -> tuple[str, bool]:
    """Возвращает (текст с маскировкой, был ли что-то замаскировано)."""
    masked = text
    for pattern in _CONTACT_PATTERNS:
        masked = pattern.sub(MASK, masked)
    return masked, masked != text


async def _has_paid_order(
    session: AsyncSession, customer_id: uuid.UUID, provider_user_id: uuid.UUID
) -> bool:
    result = await session.scalar(
        sa.select(Order.id)
        .where(
            Order.customer_id == customer_id,
            Order.provider_user_id == provider_user_id,
            Order.status == OrderStatus.PAID,
        )
        .limit(1)
    )
    return result is not None


async def get_or_create_thread(
    session: AsyncSession, me: User, peer_id: uuid.UUID, order_id: uuid.UUID | None = None
) -> ChatThread:
    if peer_id == me.id:
        raise ForbiddenError("Нельзя открыть чат с самим собой")
    peer = await session.get(User, peer_id)
    if peer is None:
        raise NotFoundError("Пользователь не найден")

    # Определяем, кто в паре заказчик, а кто исполнитель: диалог всегда
    # привязан к анкете исполнителя.
    peer_is_provider = await session.get(ProviderProfile, peer_id) is not None
    if peer_is_provider:
        customer_id, provider_user_id = me.id, peer_id
    elif await session.get(ProviderProfile, me.id) is not None:
        customer_id, provider_user_id = peer_id, me.id
    else:
        raise ForbiddenError("Чат доступен только с исполнителем")

    thread = await session.scalar(
        sa.select(ChatThread).where(
            ChatThread.customer_id == customer_id,
            ChatThread.provider_user_id == provider_user_id,
        )
    )
    if thread is None:
        thread = ChatThread(
            customer_id=customer_id,
            provider_user_id=provider_user_id,
            last_order_id=order_id,
        )
        session.add(thread)
        await session.flush()
    elif order_id is not None:
        thread.last_order_id = order_id

    # Разблокировка контактов, если между парой уже был оплаченный заказ.
    if thread.contacts_unlocked_at is None and await _has_paid_order(
        session, customer_id, provider_user_id
    ):
        thread.contacts_unlocked_at = datetime.now(UTC)
    return thread


async def get_thread_for(session: AsyncSession, me: User, thread_id: uuid.UUID) -> ChatThread:
    thread = await session.get(ChatThread, thread_id)
    if thread is None or me.id not in (thread.customer_id, thread.provider_user_id):
        raise NotFoundError("Диалог не найден")
    return thread


async def list_threads(session: AsyncSession, me: User) -> list[ChatThread]:
    rows = await session.scalars(
        sa.select(ChatThread)
        .where(
            sa.or_(ChatThread.customer_id == me.id, ChatThread.provider_user_id == me.id),
            ChatThread.is_blocked.is_(False),
        )
        .order_by(ChatThread.last_message_at.desc().nulls_last())
    )
    return list(rows)


async def send_message(
    session: AsyncSession,
    me: User,
    thread_id: uuid.UUID,
    body: str,
    *,
    message_type: MessageType = MessageType.TEXT,
    attachment_key: str | None = None,
    duration_seconds: int | None = None,
) -> ChatMessage:
    thread = await get_thread_for(session, me, thread_id)
    if thread.is_blocked:
        raise ForbiddenError("Диалог заблокирован")

    if thread.contacts_unlocked_at is None and await _has_paid_order(
        session, thread.customer_id, thread.provider_user_id
    ):
        thread.contacts_unlocked_at = datetime.now(UTC)

    # Маскируем только текст: подпись к фото тоже может содержать номер.
    if thread.contacts_unlocked_at is not None or not body:
        visible, was_masked = body, False
    else:
        visible, was_masked = mask_contacts(body)

    message = ChatMessage(
        thread_id=thread.id,
        sender_id=me.id,
        message_type=message_type,
        body=visible,
        raw_body=body if was_masked else None,
        contacts_masked=was_masked,
        attachment_key=attachment_key,
        duration_seconds=duration_seconds,
    )
    session.add(message)
    thread.last_message_at = datetime.now(UTC)
    await session.flush()

    peer_id = (
        thread.provider_user_id if me.id == thread.customer_id else thread.customer_id
    )
    sender_name = me.first_name or "Новое сообщение"
    preview = {
        MessageType.IMAGE: "📷 Фото",
        MessageType.AUDIO: "🎤 Голосовое сообщение",
    }.get(message_type, (visible or "")[:120])
    await notify_user(
        session,
        peer_id,
        sender_name,
        preview,
        {"thread_id": str(thread.id)},
    )
    return message


async def list_messages(
    session: AsyncSession, me: User, thread_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[ChatMessage], int]:
    thread = await get_thread_for(session, me, thread_id)
    base = sa.select(ChatMessage).where(ChatMessage.thread_id == thread.id)
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(base.subquery())
    )
    rows = await session.scalars(
        base.order_by(ChatMessage.created_at.desc()).limit(limit).offset(offset)
    )
    # Прочитано: помечаем чужие сообщения при чтении ленты.
    now = datetime.now(UTC)
    messages = list(rows)
    for message in messages:
        if message.sender_id != me.id and message.read_at is None:
            message.read_at = now
    return messages, int(total or 0)
