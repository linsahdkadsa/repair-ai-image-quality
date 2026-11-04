from __future__ import annotations

from typing import Protocol

from core.models import ArtifactRecord


class ArtifactWriter(Protocol):
    def save(self, record: ArtifactRecord, content: bytes) -> None: ...
