from __future__ import annotations

import errno
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.errors import AppError
from repo.artifact_repository import ArtifactRepository
from service.upload_service import UploadService


def fixture_png() -> bytes:
    return (
        Path(__file__).parents[3] / "tests" / "fixtures" / "images" / "B01_02.png"
    ).read_bytes()


def test_expired_upload_cannot_be_reused(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    service = UploadService(
        ArtifactRepository(tmp_path),
        max_bytes=200_000,
        max_pixels=2_000_000,
        ttl_seconds=1,
        clock=lambda: now,
    )
    created = service.create("operator-a", "image.png", "image/png", fixture_png())
    service.clock = lambda: now + timedelta(seconds=2)

    with pytest.raises(AppError, match="UPLOAD_EXPIRED"):
        service.bind(created.artifact_id, "operator-a", "task-1")


def test_upload_reference_is_single_use(tmp_path: Path) -> None:
    service = UploadService(
        ArtifactRepository(tmp_path),
        max_bytes=200_000,
        max_pixels=2_000_000,
        ttl_seconds=3600,
    )
    created = service.create("operator-a", "image.png", "image/png", fixture_png())
    service.bind(created.artifact_id, "operator-a", "task-1")

    with pytest.raises(AppError, match="UPLOAD_ALREADY_REFERENCED"):
        service.bind(created.artifact_id, "operator-a", "task-2")


def test_disk_full_is_reported_as_storage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = ArtifactRepository(tmp_path)
    service = UploadService(
        repository,
        max_bytes=200_000,
        max_pixels=2_000_000,
        ttl_seconds=3600,
    )

    def fail_save(*_: object, **__: object) -> None:
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(repository, "save", fail_save)

    with pytest.raises(AppError, match="STORAGE_FULL"):
        service.create("operator-a", "image.png", "image/png", fixture_png())
