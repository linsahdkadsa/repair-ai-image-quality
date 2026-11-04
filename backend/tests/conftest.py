from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from core.config import (
    AppSettings,
    AuthSettings,
    CredentialSettings,
    DataSettings,
    LoggingSettings,
    ModelSettings,
    ServerSettings,
    UploadSettings,
)
from infra.auth import hash_password


def basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def app_settings(tmp_path: Path) -> AppSettings:
    credentials = [
        CredentialSettings(
            username="operator-a",
            role="operator",
            password_hash=hash_password("operator-a-password"),
        ),
        CredentialSettings(
            username="operator-b",
            role="operator",
            password_hash=hash_password("operator-b-password"),
        ),
        CredentialSettings(
            username="viewer",
            role="viewer",
            password_hash=hash_password("viewer-password"),
        ),
        CredentialSettings(
            username="admin",
            role="admin",
            password_hash=hash_password("admin-password"),
        ),
        CredentialSettings(
            username="expired",
            role="operator",
            password_hash=hash_password("expired-password"),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        ),
    ]
    return AppSettings(
        server=ServerSettings(public_origin="http://testserver"),
        data=DataSettings(root=tmp_path / "data"),
        auth=AuthSettings(credentials=credentials, source="inline"),
        upload=UploadSettings(max_bytes=200_000, max_pixels=2_000_000, ttl_seconds=3600),
        models=ModelSettings(required_paths=[]),
        logging=LoggingSettings(path=tmp_path / "logs" / "app.jsonl"),
    )


@pytest.fixture
def client(app_settings: AppSettings) -> Iterator[TestClient]:
    with TestClient(create_app(app_settings)) as test_client:
        yield test_client


@pytest.fixture
def operator_a_auth() -> dict[str, str]:
    return basic_auth("operator-a", "operator-a-password")


@pytest.fixture
def operator_b_auth() -> dict[str, str]:
    return basic_auth("operator-b", "operator-b-password")


@pytest.fixture
def viewer_auth() -> dict[str, str]:
    return basic_auth("viewer", "viewer-password")


@pytest.fixture
def admin_auth() -> dict[str, str]:
    return basic_auth("admin", "admin-password")


@pytest.fixture
def valid_png() -> bytes:
    fixture = Path(__file__).parents[2] / "tests" / "fixtures" / "images" / "B01_02.png"
    return fixture.read_bytes()
