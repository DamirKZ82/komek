"""Документы верификации: загрузка исполнителем, просмотр и решение модератора."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from app.api.deps import CurrentStaff, CurrentUser, SessionDep
from app.core.config import settings
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.models.enums import ConsentType, DocumentStatus, DocumentType
from app.models.provider import ProviderProfile
from app.models.user import UserConsent
from app.models.verification import DocumentAccessLog, VerificationDocument
from app.schemas.document import DocumentDecisionIn, DocumentOut
from app.services.storage import get_document_storage, make_document_key, sha256_hex

router = APIRouter(tags=["documents"])

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 МБ
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}
# Справки eGov принимаются только в PDF (шаг 1 флоу, п. 4.2 ТЗ).
EGOV_PDF_ONLY_TYPES = {
    DocumentType.CRIMINAL_RECORD,
    DocumentType.PSYCH_DISPENSARY,
    DocumentType.NARCO_DISPENSARY,
}


def _validity_days(document_type: DocumentType) -> int | None:
    """Внутренние нормативы сроков действия справок (п. 4.2 ТЗ)."""
    if document_type == DocumentType.CRIMINAL_RECORD:
        return settings.criminal_record_validity_days
    if document_type in (DocumentType.PSYCH_DISPENSARY, DocumentType.NARCO_DISPENSARY):
        return settings.dispensary_validity_days
    return None


async def _require_background_check_consent(session: SessionDep, user_id: uuid.UUID) -> None:
    """Загрузка справок — только после явного согласия на обработку ПДн (п. 4.2 ТЗ)."""
    consent = await session.scalar(
        sa.select(UserConsent).where(
            UserConsent.user_id == user_id,
            UserConsent.consent_type == ConsentType.BACKGROUND_CHECK,
            UserConsent.revoked_at.is_(None),
        )
    )
    if consent is None:
        raise ForbiddenError(
            "Нужно согласие на проверку документов", code="consent_required"
        )


@router.post("/me/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    user: CurrentUser,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    document_type: Annotated[DocumentType, Form()],
    egov_reference: Annotated[str | None, Form()] = None,
    issued_at: Annotated[date | None, Form()] = None,
) -> DocumentOut:
    await _require_background_check_consent(session, user.id)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise AppError("Файл больше 15 МБ", code="file_too_large")
    if document_type in EGOV_PDF_ONLY_TYPES:
        if file.content_type != "application/pdf" or not content.startswith(b"%PDF"):
            raise AppError(
                "Справки eGov принимаются только в формате PDF",
                code="pdf_required",
            )
        # Дата выдачи не старше срока действия (шаг 1 флоу).
        validity = _validity_days(document_type)
        if (
            issued_at is not None
            and validity is not None
            and issued_at < date.today() - timedelta(days=validity)
        ):
            raise AppError(
                "Справка просрочена — получите свежую в eGov",
                code="document_expired",
            )
        # TODO(этап 1.5): автоматическое извлечение QR из PDF и проверка по eGov.
    elif file.content_type not in ALLOWED_CONTENT_TYPES:
        raise AppError(
            "Допустимы JPEG, PNG, WebP или PDF", code="unsupported_file_type"
        )

    # Повторная загрузка того же типа заменяет ожидающий документ.
    previous = await session.scalars(
        sa.select(VerificationDocument).where(
            VerificationDocument.user_id == user.id,
            VerificationDocument.document_type == document_type,
            VerificationDocument.status == DocumentStatus.PENDING,
        )
    )
    storage = get_document_storage()
    for old in previous:
        await storage.delete(old.storage_key)
        await session.delete(old)

    key = make_document_key(str(user.id), document_type.value, file.filename)
    await storage.put(key, content, file.content_type)

    document = VerificationDocument(
        user_id=user.id,
        document_type=document_type,
        storage_key=key,
        file_name=file.filename,
        content_type=file.content_type,
        file_size=len(content),
        checksum_sha256=sha256_hex(content),
        egov_reference=egov_reference,
        issued_at=issued_at,
    )
    session.add(document)
    await session.flush()
    return DocumentOut.model_validate(document)


@router.get("/me/documents", response_model=list[DocumentOut])
async def my_documents(user: CurrentUser, session: SessionDep) -> list[DocumentOut]:
    rows = await session.scalars(
        sa.select(VerificationDocument)
        .where(VerificationDocument.user_id == user.id)
        .order_by(VerificationDocument.created_at.desc())
    )
    return [DocumentOut.model_validate(d) for d in rows]


# --- Модерация ----------------------------------------------------------------


async def _log_access(
    session: SessionDep,
    request: Request,
    document: VerificationDocument,
    actor_id: uuid.UUID,
    action: str,
) -> None:
    session.add(
        DocumentAccessLog(
            document_id=document.id,
            actor_id=actor_id,
            action=action,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )


@router.get("/admin/users/{user_id}/documents", response_model=list[DocumentOut])
async def user_documents(
    user_id: uuid.UUID, staff: CurrentStaff, session: SessionDep
) -> list[DocumentOut]:
    rows = await session.scalars(
        sa.select(VerificationDocument)
        .where(VerificationDocument.user_id == user_id)
        .order_by(VerificationDocument.created_at.desc())
    )
    return [DocumentOut.model_validate(d) for d in rows]


@router.get("/admin/documents/{document_id}/file")
async def download_document(
    document_id: uuid.UUID, staff: CurrentStaff, session: SessionDep, request: Request
) -> Response:
    """Просмотр файла модератором. Каждый доступ пишется в журнал (закон о ПДн)."""
    document = await session.get(VerificationDocument, document_id)
    if document is None:
        raise NotFoundError("Документ не найден")
    try:
        content = await get_document_storage().get(document.storage_key)
    except FileNotFoundError as exc:
        raise NotFoundError("Файл отсутствует в хранилище") from exc
    await _log_access(session, request, document, staff.id, "view")
    return Response(
        content=content,
        media_type=document.content_type or "application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/admin/documents/{document_id}/decision", response_model=DocumentOut)
async def decide_document(
    document_id: uuid.UUID,
    data: DocumentDecisionIn,
    staff: CurrentStaff,
    session: SessionDep,
    request: Request,
) -> DocumentOut:
    document = await session.get(VerificationDocument, document_id, with_for_update=True)
    if document is None:
        raise NotFoundError("Документ не найден")

    document.reviewed_by_id = staff.id
    document.reviewed_at = datetime.now(UTC)
    if data.iin is not None:
        document.iin = data.iin

    # Шаг 4 (ТЗ 4.2): ИИН справки должен совпадать с ИИН удостоверения того же
    # исполнителя — иначе можно загрузить чужие «чистые» справки.
    approve = data.approve
    rejection_reason = data.rejection_reason
    if approve and document.iin is not None:
        id_card_iin = await session.scalar(
            sa.select(VerificationDocument.iin).where(
                VerificationDocument.user_id == document.user_id,
                VerificationDocument.document_type == DocumentType.ID_CARD,
                VerificationDocument.status == DocumentStatus.APPROVED,
                VerificationDocument.iin.is_not(None),
            )
        )
        if id_card_iin is not None and id_card_iin != document.iin:
            approve = False
            rejection_reason = (
                "ИИН в справке не совпадает с ИИН удостоверения — документ отклонён"
            )

    if approve:
        document.status = DocumentStatus.APPROVED
        if data.valid_until is not None:
            document.valid_until = data.valid_until
        else:
            validity = _validity_days(document.document_type)
            if validity is not None:
                base = document.issued_at or date.today()
                document.valid_until = base + timedelta(days=validity)
    else:
        document.status = DocumentStatus.REJECTED
        document.rejection_reason = rejection_reason

    await _log_access(session, request, document, staff.id, "decide")

    # Ближайший срок протухания справок — на профиль исполнителя (п. 4.2 ТЗ).
    if approve and document.valid_until is not None:
        profile = await session.get(ProviderProfile, document.user_id)
        if profile is not None and (
            profile.documents_valid_until is None
            or document.valid_until < profile.documents_valid_until
        ):
            profile.documents_valid_until = document.valid_until
    return DocumentOut.model_validate(document)
