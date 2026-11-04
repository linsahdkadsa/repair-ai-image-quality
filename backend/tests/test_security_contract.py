from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from conftest import basic_auth
from fastapi.testclient import TestClient

from api.app import create_app
from core.config import AppSettings, AuthSettings
from infra.auth import hash_password
from infra.logging import sanitize_log_message


def test_private_route_requires_credentials(client: TestClient) -> None:
    response = client.get("/api/v1/session")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_REQUIRED"
    assert response.headers["x-trace-id"] == response.json()["trace_id"]


def test_session_uses_named_identity(client: TestClient, operator_a_auth: dict[str, str]) -> None:
    response = client.get("/api/v1/session", headers=operator_a_auth)

    assert response.status_code == 200
    assert response.json()["data"] == {
        "username": "operator-a",
        "role": "operator",
        "authMethod": "basic",
    }
    assert "password" not in response.text.lower()


@pytest.mark.parametrize(
    "headers",
    [
        basic_auth("operator-a", "wrong-password"),
        basic_auth("expired", "expired-password"),
        {"Authorization": "Basic not-base64"},
    ],
)
def test_wrong_expired_or_malformed_credentials_are_rejected(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/session", headers=headers)

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_INVALID"


def test_viewer_cannot_create_upload(
    client: TestClient, viewer_auth: dict[str, str], valid_png: bytes
) -> None:
    response = client.post(
        "/api/v1/uploads",
        headers=viewer_auth,
        files={"file": ("image.png", valid_png, "image/png")},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ROLE_FORBIDDEN"


def test_operator_cannot_read_other_users_upload(
    client: TestClient,
    operator_a_auth: dict[str, str],
    operator_b_auth: dict[str, str],
    valid_png: bytes,
) -> None:
    uploaded = client.post(
        "/api/v1/uploads",
        headers=operator_a_auth,
        files={"file": ("image.png", valid_png, "image/png")},
    ).json()["data"]["uploadId"]

    response = client.delete(f"/api/v1/uploads/{uploaded}", headers=operator_b_auth)

    assert response.status_code == 404
    assert response.json()["error_code"] == "UPLOAD_NOT_FOUND"
    assert response.headers["x-trace-id"] == response.json()["trace_id"]


def test_invalid_trace_is_replaced_and_valid_trace_is_preserved(
    client: TestClient, operator_a_auth: dict[str, str]
) -> None:
    invalid = client.get(
        "/api/v1/session",
        headers={**operator_a_auth, "X-Trace-Id": "bad trace value"},
    )
    valid = client.get(
        "/api/v1/session",
        headers={**operator_a_auth, "X-Trace-Id": "client-trace-1234"},
    )

    assert invalid.headers["x-trace-id"] != "bad trace value"
    assert valid.headers["x-trace-id"] == "client-trace-1234"


@pytest.mark.parametrize("path", ["/healthz", "/api/v1/session", "/missing"])
def test_security_headers_cover_public_private_and_error_responses(
    client: TestClient, operator_a_auth: dict[str, str], path: str
) -> None:
    response = client.get(path, headers=operator_a_auth)

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


def test_hsts_is_only_enabled_for_https(app_settings: AppSettings) -> None:
    secure = app_settings.model_copy(
        update={"server": app_settings.server.model_copy(update={"https": True})}
    )
    with TestClient(create_app(secure)) as client:
        response = client.get("/healthz")

    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_environment_server_settings_reach_security_middleware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "server": {
                    "https": True,
                    "public_origin": "https://repair.example",
                },
                "data": {"root": str(tmp_path / "data")},
                "logging": {"path": str(tmp_path / "logs" / "app.jsonl")},
                "auth": {
                    "credentials": [
                        {
                            "username": "admin",
                            "role": "admin",
                            "password_hash": hash_password("admin-password"),
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    for key in tuple(os.environ):
        if key.startswith("RAI_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("RAI_CONFIG_PATH", str(config_path))

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/session/reload-credentials",
            headers={
                **basic_auth("admin", "admin-password"),
                "Origin": "https://repair.example",
            },
        )

    assert response.status_code != 403
    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_cross_origin_write_is_rejected(
    client: TestClient, operator_a_auth: dict[str, str], valid_png: bytes
) -> None:
    response = client.post(
        "/api/v1/uploads",
        headers={**operator_a_auth, "Origin": "https://attacker.example"},
        files={"file": ("image.png", valid_png, "image/png")},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ORIGIN_FORBIDDEN"


def test_file_credentials_reload_rejects_old_password_on_next_request(
    tmp_path: Path, app_settings: AppSettings
) -> None:
    credentials_path = tmp_path / "credentials.yaml"
    credentials_path.write_text(
        yaml.safe_dump(
            {
                "users": [
                    {
                        "username": "admin",
                        "role": "admin",
                        "password_hash": hash_password("old-password"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = app_settings.model_copy(
        update={
            "auth": AuthSettings(credentials_file=credentials_path, source="file"),
        }
    )

    with TestClient(create_app(settings)) as client:
        initial = client.get(
            "/api/v1/session", headers=basic_auth("admin", "old-password")
        )
        assert initial.status_code == 200
        credentials_path.write_text(
            yaml.safe_dump(
                {
                    "users": [
                        {
                            "username": "admin",
                            "role": "admin",
                            "password_hash": hash_password("new-password"),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        reloaded = client.post(
            "/api/v1/session/reload-credentials",
            headers=basic_auth("admin", "old-password"),
        )
        old = client.get("/api/v1/session", headers=basic_auth("admin", "old-password"))
        new = client.get("/api/v1/session", headers=basic_auth("admin", "new-password"))

    assert reloaded.status_code == 200
    assert old.status_code == 401
    assert new.status_code == 200


def test_environment_credentials_require_restart(
    client: TestClient, admin_auth: dict[str, str]
) -> None:
    response = client.post("/api/v1/session/reload-credentials", headers=admin_auth)

    assert response.status_code == 409
    assert response.json()["error_code"] == "AUTH_RESTART_REQUIRED"


def test_only_admin_can_read_log_diagnostics(
    client: TestClient,
    operator_a_auth: dict[str, str],
    admin_auth: dict[str, str],
) -> None:
    forbidden = client.get("/api/v1/system/status", headers=operator_a_auth)
    allowed = client.get("/api/v1/system/status", headers=admin_auth)

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["data"]["logging"] == {
        "writeFailures": 0,
        "droppedRecords": 0,
    }


def test_readiness_reports_required_model_without_exposing_path(
    app_settings: AppSettings, tmp_path: Path
) -> None:
    missing = tmp_path / "private" / "missing-model.onnx"
    settings = app_settings.model_copy(
        update={
            "models": app_settings.models.model_copy(update={"required_paths": [missing]})
        }
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "ready": False,
        "reason": "required_model_missing",
    }
    assert str(missing) not in response.text


def test_log_sanitizer_removes_credentials_cookies_and_secret_samples() -> None:
    message = (
        "Authorization: Basic dXNlcjpwYXNz Cookie: session=top-secret "
        "password_hash=scrypt$sample"
    )

    sanitized = sanitize_log_message(message)

    assert "dXNlcjpwYXNz" not in sanitized
    assert "top-secret" not in sanitized
    assert "scrypt$sample" not in sanitized
