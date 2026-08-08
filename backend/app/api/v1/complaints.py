from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.schemas.moderation import ComplaintIn, ComplaintOut
from app.services import moderation as moderation_service

router = APIRouter(prefix="/complaints", tags=["complaints"])


@router.post("", response_model=ComplaintOut, status_code=201)
async def file_complaint(
    data: ComplaintIn, user: CurrentUser, session: SessionDep
) -> ComplaintOut:
    complaint = await moderation_service.file_complaint(session, user, data)
    return ComplaintOut.model_validate(complaint)
