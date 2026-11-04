from __future__ import annotations

from fastapi.testclient import TestClient

from core.config import AppSettings


def test_valid_upload_returns_private_metadata(
    client: TestClient, operator_a_auth: dict[str, str], valid_png: bytes
) -> None:
    response = client.post(
        "/api/v1/uploads",
        headers=operator_a_auth,
        files={"file": ("image.png", valid_png, "image/png")},
    )

    assert response.status_code == 201
    assert set(response.json()["data"]) == {
        "uploadId",
        "width",
        "height",
        "format",
        "sizeBytes",
        "sha256",
        "expiresAt",
        "originalName",
    }
    assert "path" not in response.text.lower()


def test_fake_extension_is_rejected(
    client: TestClient, operator_a_auth: dict[str, str], valid_png: bytes
) -> None:
    response = client.post(
        "/api/v1/uploads",
        headers=operator_a_auth,
        files={"file": ("fake.jpg", valid_png, "image/jpeg")},
    )

    assert response.status_code == 415
    assert response.json()["error_code"] == "IMAGE_TYPE_MISMATCH"


def test_decode_failure_is_rejected(client: TestClient, operator_a_auth: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/uploads",
        headers=operator_a_auth,
        files={"file": ("broken.png", b"not-an-image", "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "IMAGE_DECODE_FAILED"


def test_empty_upload_is_rejected(client: TestClient, operator_a_auth: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/uploads",
        headers=operator_a_auth,
        files={"file": ("empty.png", b"", "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "UPLOAD_EMPTY"


def test_size_limit_is_enforced(
    app_settings: AppSettings, operator_a_auth: dict[str, str], valid_png: bytes
) -> None:
    from api.app import create_app

    limited = app_settings.model_copy(
        update={"upload": app_settings.upload.model_copy(update={"max_bytes": 10})}
    )
    with TestClient(create_app(limited)) as client:
        response = client.post(
            "/api/v1/uploads",
            headers=operator_a_auth,
            files={"file": ("image.png", valid_png, "image/png")},
        )

    assert response.status_code == 413
    assert response.json()["error_code"] == "UPLOAD_TOO_LARGE"


def test_pixel_limit_is_enforced(
    app_settings: AppSettings, operator_a_auth: dict[str, str], valid_png: bytes
) -> None:
    from api.app import create_app

    limited = app_settings.model_copy(
        update={"upload": app_settings.upload.model_copy(update={"max_pixels": 1})}
    )
    with TestClient(create_app(limited)) as client:
        response = client.post(
            "/api/v1/uploads",
            headers=operator_a_auth,
            files={"file": ("image.png", valid_png, "image/png")},
        )

    assert response.status_code == 413
    assert response.json()["error_code"] == "IMAGE_PIXELS_EXCEEDED"


def test_user_filename_cannot_escape_data_root(
    client: TestClient,
    app_settings: AppSettings,
    operator_a_auth: dict[str, str],
    valid_png: bytes,
) -> None:
    response = client.post(
        "/api/v1/uploads",
        headers=operator_a_auth,
        files={"file": ("../../outside.png", valid_png, "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["data"]["originalName"] == "outside.png"
    assert not (app_settings.data.root.parent / "outside.png").exists()
    assert all(
        path.resolve().is_relative_to(app_settings.data.root.resolve())
        for path in app_settings.data.root.rglob("*")
    )
