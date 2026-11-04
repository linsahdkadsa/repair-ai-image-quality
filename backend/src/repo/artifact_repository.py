from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from core.errors import app_error
from core.models import ArtifactRecord

ARTIFACT_ID_PATTERN = re.compile(r"^upl_[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class StoredArtifact:
    record: ArtifactRecord
    content: bytes


class ArtifactRepository:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.upload_root = self.data_root / "uploads"
        self.lock_path = self.data_root / ".instance.lock"
        self._lock_fd: int | None = None
        self.upload_root.mkdir(parents=True, exist_ok=True)

    def acquire_instance_lock(self) -> None:
        if self._lock_fd is not None:
            return
        self.data_root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise app_error("DATA_ROOT_LOCKED", cause=exc) from exc
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
        except OSError:
            os.close(descriptor)
            self.lock_path.unlink(missing_ok=True)
            raise
        self._lock_fd = descriptor

    def release_instance_lock(self) -> None:
        if self._lock_fd is None:
            return
        os.close(self._lock_fd)
        self._lock_fd = None
        self.lock_path.unlink(missing_ok=True)

    def save(self, record: ArtifactRecord, content: bytes) -> None:
        artifact_dir = self._artifact_dir(record.artifact_id)
        artifact_dir.mkdir(parents=True, exist_ok=False)
        try:
            self._atomic_write(artifact_dir / "content.bin", content)
            self._atomic_write(
                artifact_dir / "metadata.json",
                self._serialize_record(record),
            )
        except Exception:
            for child in artifact_dir.iterdir():
                child.unlink(missing_ok=True)
            artifact_dir.rmdir()
            raise

    def get(self, artifact_id: str, *, owner_id: str) -> StoredArtifact | None:
        try:
            artifact_dir = self._artifact_dir(artifact_id)
        except ValueError:
            return None
        metadata_path = artifact_dir / "metadata.json"
        content_path = artifact_dir / "content.bin"
        try:
            record = self._deserialize_record(metadata_path.read_text(encoding="utf-8"))
            content = content_path.read_bytes()
        except FileNotFoundError:
            return None
        if record.owner_id != owner_id:
            return None
        return StoredArtifact(record=record, content=content)

    def update(self, record: ArtifactRecord) -> None:
        artifact_dir = self._artifact_dir(record.artifact_id)
        if not (artifact_dir / "content.bin").is_file():
            raise FileNotFoundError(record.artifact_id)
        self._atomic_write(
            artifact_dir / "metadata.json",
            self._serialize_record(record),
        )

    def delete(self, artifact_id: str, *, owner_id: str) -> bool:
        stored = self.get(artifact_id, owner_id=owner_id)
        if stored is None:
            return False
        artifact_dir = self._artifact_dir(artifact_id)
        for child in artifact_dir.iterdir():
            child.unlink(missing_ok=True)
        artifact_dir.rmdir()
        return True

    def _artifact_dir(self, artifact_id: str) -> Path:
        if ARTIFACT_ID_PATTERN.fullmatch(artifact_id) is None:
            raise ValueError("artifact id 格式无效")
        target = (self.upload_root / artifact_id).resolve()
        if not target.is_relative_to(self.upload_root.resolve()):
            raise ValueError("artifact id 越出 data root")
        return target

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _serialize_record(record: ArtifactRecord) -> bytes:
        value = asdict(record)
        value["expires_at"] = record.expires_at.isoformat()
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _deserialize_record(value: str) -> ArtifactRecord:
        payload = json.loads(value)
        expected = {field.name for field in fields(ArtifactRecord)}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("artifact metadata 字段无效")
        payload["expires_at"] = datetime.fromisoformat(payload["expires_at"])
        return ArtifactRecord(**payload)
