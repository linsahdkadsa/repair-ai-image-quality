from __future__ import annotations

import errno
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from core.errors import app_error
from core.models import ArtifactRecord
from repo.artifact_repository import ArtifactRepository, StoredArtifact

FORMAT_CONTRACTS: dict[str, tuple[set[str], set[str]]] = {
    "JPEG": ({".jpg", ".jpeg"}, {"image/jpeg"}),
    "PNG": ({".png"}, {"image/png"}),
    "WEBP": ({".webp"}, {"image/webp"}),
}


class UploadService:
    def __init__(
        self,
        repository: ArtifactRepository,
        *,
        max_bytes: int,
        max_pixels: int,
        ttl_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.max_bytes = max_bytes
        self.max_pixels = max_pixels
        self.ttl_seconds = ttl_seconds
        self.clock = clock or (lambda: datetime.now(UTC))

    def create(
        self,
        owner_id: str,
        original_name: str,
        media_type: str,
        content: bytes,
    ) -> ArtifactRecord:
        if not content:
            raise app_error("UPLOAD_EMPTY")
        if len(content) > self.max_bytes:
            raise app_error("UPLOAD_TOO_LARGE")

        image_format, width, height, orientation = self._inspect_image(content)
        if width * height > self.max_pixels:
            raise app_error("IMAGE_PIXELS_EXCEEDED")

        display_name = self._display_name(original_name)
        self._validate_type(display_name, media_type, image_format)
        now = self._utc(self.clock())
        record = ArtifactRecord(
            artifact_id=f"upl_{secrets.token_urlsafe(18)}",
            owner_id=owner_id,
            original_name=display_name,
            media_type=media_type.lower(),
            image_format=image_format,
            width=width,
            height=height,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            exif_orientation=orientation,
        )
        try:
            self.repository.save(record, content)
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise app_error("STORAGE_FULL", cause=exc) from exc
            raise
        return record

    def get(self, artifact_id: str, owner_id: str) -> StoredArtifact:
        stored = self.repository.get(artifact_id, owner_id=owner_id)
        if stored is None:
            raise app_error("UPLOAD_NOT_FOUND")
        return stored

    def delete(self, artifact_id: str, owner_id: str) -> None:
        if not self.repository.delete(artifact_id, owner_id=owner_id):
            raise app_error("UPLOAD_NOT_FOUND")

    def bind(self, artifact_id: str, owner_id: str, reference_id: str) -> ArtifactRecord:
        stored = self.get(artifact_id, owner_id)
        if stored.record.expires_at <= self._utc(self.clock()):
            raise app_error("UPLOAD_EXPIRED")
        if stored.record.referenced_by is not None:
            raise app_error("UPLOAD_ALREADY_REFERENCED")
        updated = replace(stored.record, referenced_by=reference_id, version=2)
        self.repository.update(updated)
        return updated

    @staticmethod
    def _inspect_image(content: bytes) -> tuple[str, int, int, int | None]:
        try:
            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                width, height = image.size
                image.verify()
            with Image.open(BytesIO(content)) as image:
                orientation = image.getexif().get(274)
        except (UnidentifiedImageError, OSError, RuntimeError, ValueError) as exc:
            raise app_error("IMAGE_DECODE_FAILED", cause=exc) from exc
        if image_format not in FORMAT_CONTRACTS:
            raise app_error("IMAGE_TYPE_MISMATCH")
        return image_format, width, height, orientation

    @staticmethod
    def _display_name(value: str) -> str:
        normalized = value.replace("\\", "/")
        return normalized.rsplit("/", 1)[-1] or "upload"

    @staticmethod
    def _validate_type(original_name: str, media_type: str, image_format: str) -> None:
        suffix = "." + original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        extensions, media_types = FORMAT_CONTRACTS[image_format]
        if suffix not in extensions or media_type.lower() not in media_types:
            raise app_error("IMAGE_TYPE_MISMATCH")

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
