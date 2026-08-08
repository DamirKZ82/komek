from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import MessageType
from app.schemas.common import ApiModel


class ThreadCreateIn(BaseModel):
    peer_user_id: uuid.UUID
    order_id: uuid.UUID | None = None


class ThreadPeer(BaseModel):
    id: uuid.UUID
    first_name: str | None
    last_name: str | None
    avatar_key: str | None
    # Значок «проверенный»: исполнителю важно знать, к кому он едет (п. 4.3 ТЗ).
    identity_verified: bool = False


class ThreadOut(BaseModel):
    id: uuid.UUID
    peer: ThreadPeer
    last_order_id: uuid.UUID | None
    contacts_unlocked: bool
    last_message_at: datetime | None
    last_message_preview: str | None = None
    unread_count: int = 0


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class MessageOut(ApiModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    sender_id: uuid.UUID | None
    message_type: MessageType
    body: str | None
    contacts_masked: bool
    # Наружу отдаём факт наличия вложения, но не ключ в хранилище:
    # файл забирается через /chats/{thread}/attachments/{message}.
    has_attachment: bool = False
    duration_seconds: int | None = None
    read_at: datetime | None
    created_at: datetime

    @classmethod
    def from_message(cls, message: object) -> MessageOut:
        out = cls.model_validate(message)
        out.has_attachment = getattr(message, "attachment_key", None) is not None
        return out
