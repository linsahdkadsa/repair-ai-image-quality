from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    owner_id: str
    original_name: str
    media_type: str
    image_format: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    expires_at: datetime
    schema_version: int = 1
    version: int = 1
    referenced_by: str | None = None
    exif_orientation: int | None = None
