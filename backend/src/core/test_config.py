from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.config import ConfigError, load_settings


def write_yaml(path: Path, value: object) -> Path:
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")
    return path


def credentials_file(tmp_path: Path) -> Path:
    return write_yaml(
        tmp_path / "credentials.yaml",
        {
            "users": [
                {
                    "username": "operator",
                    "role": "operator",
                    "password_hash": "test-password-hash",
                }
            ]
        },
    )


def test_config_precedence_defaults_global_instance_then_env(tmp_path: Path) -> None:
    creds = credentials_file(tmp_path)
    global_path = write_yaml(
        tmp_path / "global.yaml",
        {
            "data": {"root": str(tmp_path / "global-data")},
            "auth": {"credentials_file": str(creds)},
            "upload": {"max_bytes": 1000, "max_pixels": 2000},
        },
    )
    instance_path = write_yaml(
        tmp_path / "instance.yaml",
        {"upload": {"max_bytes": 1500}},
    )

    settings = load_settings(
        global_path=global_path,
        instance_path=instance_path,
        env={"RAI_UPLOAD_MAX_BYTES": "2000"},
    )

    assert settings.upload.max_bytes == 2000
    assert settings.upload.max_pixels == 2000
    assert settings.data.root == tmp_path / "global-data"
    assert settings.source_summary["upload.max_bytes"] == "env:RAI_UPLOAD_MAX_BYTES"


def test_unknown_global_field_is_rejected(tmp_path: Path) -> None:
    config = write_yaml(
        tmp_path / "global.yaml",
        {
            "data": {"root": str(tmp_path / "data")},
            "auth": {"credentials_file": str(credentials_file(tmp_path))},
            "surprise": True,
        },
    )

    with pytest.raises(ConfigError, match="surprise"):
        load_settings(global_path=config, env={})


@pytest.mark.parametrize("forbidden", ["auth", "data"])
def test_instance_cannot_override_security_or_isolation_fields(
    tmp_path: Path, forbidden: str
) -> None:
    global_path = write_yaml(
        tmp_path / "global.yaml",
        {
            "data": {"root": str(tmp_path / "data")},
            "auth": {"credentials_file": str(credentials_file(tmp_path))},
        },
    )
    instance_path = write_yaml(tmp_path / "instance.yaml", {forbidden: {}})

    with pytest.raises(ConfigError, match=forbidden):
        load_settings(global_path=global_path, instance_path=instance_path, env={})


def test_missing_credentials_fail_closed(tmp_path: Path) -> None:
    config = write_yaml(
        tmp_path / "global.yaml",
        {"data": {"root": str(tmp_path / "data")}},
    )

    with pytest.raises(ConfigError, match="credentials"):
        load_settings(global_path=config, env={})


def test_unwritable_data_root_fails_startup(tmp_path: Path) -> None:
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("occupied", encoding="utf-8")
    config = write_yaml(
        tmp_path / "global.yaml",
        {
            "data": {"root": str(occupied)},
            "auth": {"credentials_file": str(credentials_file(tmp_path))},
        },
    )

    with pytest.raises(ConfigError, match="data root"):
        load_settings(global_path=config, env={})


def test_non_loopback_http_is_rejected(tmp_path: Path) -> None:
    config = write_yaml(
        tmp_path / "global.yaml",
        {
            "server": {"bind_host": "0.0.0.0", "https": False},
            "data": {"root": str(tmp_path / "data")},
            "auth": {"credentials_file": str(credentials_file(tmp_path))},
        },
    )

    with pytest.raises(ConfigError, match="HTTPS"):
        load_settings(global_path=config, env={})
