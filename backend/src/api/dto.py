from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from core.models import ArtifactRecord
from infra.auth import Principal


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SessionData(ApiModel):
    username: str
    role: str
    auth_method: str

    @classmethod
    def from_principal(cls, principal: Principal) -> SessionData:
        return cls(
            username=principal.username,
            role=principal.role,
            auth_method=principal.auth_method,
        )


class SessionEnvelope(ApiModel):
    data: SessionData


class ReloadData(ApiModel):
    reloaded: bool


class ReloadEnvelope(ApiModel):
    data: ReloadData


class UploadData(ApiModel):
    upload_id: str
    width: int
    height: int
    format: str
    size_bytes: int
    sha256: str
    expires_at: datetime
    original_name: str

    @classmethod
    def from_record(cls, record: ArtifactRecord) -> UploadData:
        return cls(
            upload_id=record.artifact_id,
            width=record.width,
            height=record.height,
            format=record.image_format,
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            expires_at=record.expires_at,
            original_name=record.original_name,
        )


class UploadEnvelope(ApiModel):
    data: UploadData


class LoggingDiagnosticsData(ApiModel):
    write_failures: int
    dropped_records: int


class SystemStatusData(ApiModel):
    logging: LoggingDiagnosticsData


class SystemStatusEnvelope(ApiModel):
    data: SystemStatusData
