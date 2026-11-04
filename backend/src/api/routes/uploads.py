from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from api.dependencies import get_settings, get_upload_service, require_roles
from api.dto import UploadData, UploadEnvelope
from core.config import AppSettings
from core.errors import app_error
from infra.auth import Principal
from service.upload_service import UploadService

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


@router.post("", response_model=UploadEnvelope, status_code=status.HTTP_201_CREATED)
async def create_upload(
    principal: Annotated[Principal, Depends(require_roles("operator", "admin"))],
    service: Annotated[UploadService, Depends(get_upload_service)],
    settings: Annotated[AppSettings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
) -> UploadEnvelope:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > settings.upload.max_bytes:
            raise app_error("UPLOAD_TOO_LARGE")
        chunks.append(chunk)
    record = service.create(
        principal.username,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
        b"".join(chunks),
    )
    return UploadEnvelope(data=UploadData.from_record(record))


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(
    upload_id: str,
    principal: Annotated[Principal, Depends(require_roles("operator", "admin"))],
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> Response:
    service.delete(upload_id, principal.username)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
