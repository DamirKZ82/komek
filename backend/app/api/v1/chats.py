from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, File, Form, Response, UploadFile

from app.api.deps import CurrentUser, PaginationDep, SessionDep
from app.core.errors import AppError, NotFoundError
from app.models.chat import ChatMessage, ChatThread
from app.models.enums import MessageType
from app.models.user import User
from app.schemas.chat import MessageIn, MessageOut, ThreadCreateIn, ThreadOut, ThreadPeer
from app.schemas.common import Page
from app.services import chat as chat_service
from app.services.storage import get_media_storage, make_chat_attachment_key

router = APIRouter(prefix="/chats", tags=["chats"])


async def _thread_out(session: SessionDep, thread: ChatThread, me: User) -> ThreadOut:
    peer_id = (
        thread.provider_user_id if thread.customer_id == me.id else thread.customer_id
    )
    peer = await session.get(User, peer_id)
    last_message = await session.scalar(
        sa.select(ChatMessage)
        .where(ChatMessage.thread_id == thread.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    unread = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ChatMessage)
        .where(
            ChatMessage.thread_id == thread.id,
            ChatMessage.sender_id != me.id,
            ChatMessage.read_at.is_(None),
        )
    )
    return ThreadOut(
        id=thread.id,
        peer=ThreadPeer(
            id=peer_id,
            first_name=peer.first_name if peer else None,
            last_name=peer.last_name if peer else None,
            avatar_key=peer.avatar_key if peer else None,
            identity_verified=peer.is_identity_verified if peer else False,
        ),
        last_order_id=thread.last_order_id,
        contacts_unlocked=thread.contacts_unlocked_at is not None,
        last_message_at=thread.last_message_at,
        last_message_preview=(last_message.body or "")[:80] if last_message else None,
        unread_count=int(unread or 0),
    )


@router.get("", response_model=list[ThreadOut])
async def my_threads(user: CurrentUser, session: SessionDep) -> list[ThreadOut]:
    threads = await chat_service.list_threads(session, user)
    return [await _thread_out(session, thread, user) for thread in threads]


@router.post("", response_model=ThreadOut, status_code=201)
async def open_thread(
    data: ThreadCreateIn, user: CurrentUser, session: SessionDep
) -> ThreadOut:
    thread = await chat_service.get_or_create_thread(
        session, user, data.peer_user_id, data.order_id
    )
    return await _thread_out(session, thread, user)


@router.get("/{thread_id}/messages", response_model=Page[MessageOut])
async def thread_messages(
    thread_id: uuid.UUID, user: CurrentUser, session: SessionDep, pagination: PaginationDep
) -> Page[MessageOut]:
    messages, total = await chat_service.list_messages(
        session, user, thread_id, pagination.limit, pagination.offset
    )
    return Page(
        items=[MessageOut.from_message(m) for m in messages],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("/{thread_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    thread_id: uuid.UUID, data: MessageIn, user: CurrentUser, session: SessionDep
) -> MessageOut:
    message = await chat_service.send_message(session, user, thread_id, data.body)
    return MessageOut.from_message(message)


# --- Вложения: фото и голосовые (п. 5.4 ТЗ) -----------------------------------

MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20 МБ
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
ALLOWED_AUDIO_TYPES = {"audio/m4a", "audio/mp4", "audio/mpeg", "audio/aac", "audio/ogg"}


@router.post("/{thread_id}/attachments", response_model=MessageOut, status_code=201)
async def send_attachment(
    thread_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    caption: Annotated[str | None, Form()] = None,
    duration_seconds: Annotated[int | None, Form()] = None,
) -> MessageOut:
    """Фото или голосовое в диалог. Файлы лежат в медиа-бакете, не в документном."""
    thread = await chat_service.get_thread_for(session, user, thread_id)

    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise AppError("Файл больше 20 МБ", code="file_too_large")

    if file.content_type in ALLOWED_IMAGE_TYPES:
        message_type = MessageType.IMAGE
    elif file.content_type in ALLOWED_AUDIO_TYPES:
        message_type = MessageType.AUDIO
    else:
        raise AppError(
            "Допустимы изображения или голосовые сообщения", code="unsupported_file_type"
        )

    key = make_chat_attachment_key(str(thread.id), file.filename)
    await get_media_storage().put(key, content, file.content_type)

    message = await chat_service.send_message(
        session,
        user,
        thread_id,
        caption or "",
        message_type=message_type,
        attachment_key=key,
        duration_seconds=duration_seconds if message_type == MessageType.AUDIO else None,
    )
    return MessageOut.from_message(message)


@router.get("/{thread_id}/attachments/{message_id}")
async def download_attachment(
    thread_id: uuid.UUID, message_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    """Файл отдаётся только участникам диалога."""
    await chat_service.get_thread_for(session, user, thread_id)
    message = await session.get(ChatMessage, message_id)
    if message is None or message.thread_id != thread_id or message.attachment_key is None:
        raise NotFoundError("Вложение не найдено")
    try:
        content = await get_media_storage().get(message.attachment_key)
    except FileNotFoundError as exc:
        raise NotFoundError("Файл отсутствует в хранилище") from exc
    return Response(
        content=content,
        media_type="image/jpeg" if message.message_type == MessageType.IMAGE else "audio/m4a",
        headers={"Cache-Control": "private, max-age=3600"},
    )
