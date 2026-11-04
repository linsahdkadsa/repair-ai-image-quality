from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.errors import AppError
from core.models import ArtifactRecord
from repo.artifact_repository import ArtifactRepository


def record(artifact_id: str = "upl_valid123") -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        owner_id="operator-a",
        original_name="display.png",
        media_type="image/png",
        image_format="PNG",
        width=1,
        height=1,
        size_bytes=3,
        sha256="0" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_repository_writes_under_data_root_and_filters_owner(tmp_path: Path) -> None:
    repository = ArtifactRepository(tmp_path)

    repository.save(record(), b"png")

    stored = repository.get("upl_valid123", owner_id="operator-a")
    assert stored is not None
    assert stored.record.owner_id == "operator-a"
    assert stored.content == b"png"
    assert repository.get("upl_valid123", owner_id="operator-b") is None
    assert all(path.is_relative_to(tmp_path.resolve()) for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("artifact_id", ["../../outside", "..\\outside", "bad/id"])
def test_repository_rejects_path_like_ids(tmp_path: Path, artifact_id: str) -> None:
    repository = ArtifactRepository(tmp_path)

    with pytest.raises(ValueError, match="artifact id"):
        repository.save(record(artifact_id), b"png")


def test_repository_exclusively_locks_data_root(tmp_path: Path) -> None:
    first = ArtifactRepository(tmp_path)
    second = ArtifactRepository(tmp_path)

    first.acquire_instance_lock()
    try:
        with pytest.raises(AppError, match="DATA_ROOT_LOCKED"):
            second.acquire_instance_lock()
    finally:
        first.release_instance_lock()

    second.acquire_instance_lock()
    second.release_instance_lock()
