from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ConfigError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CredentialSettings(StrictModel):
    username: str = Field(min_length=1, max_length=128)
    role: Literal["viewer", "operator", "admin"]
    password_hash: str = Field(min_length=1)
    expires_at: datetime | None = None


class ServerSettings(StrictModel):
    bind_host: str = "127.0.0.1"
    public_origin: str = "http://127.0.0.1:3000"
    https: bool = False
    trusted_proxies: list[str] = Field(default_factory=list)


class DataSettings(StrictModel):
    root: Path = Path("data")


class AuthSettings(StrictModel):
    credentials_file: Path | None = None
    credentials: list[CredentialSettings] = Field(default_factory=list)
    source: Literal["file", "env", "inline"] = "inline"


class UploadSettings(StrictModel):
    max_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pixels: int = Field(default=40_000_000, gt=0)
    ttl_seconds: int = Field(default=24 * 60 * 60, gt=0)


class ModelSettings(StrictModel):
    required_paths: list[Path] = Field(default_factory=list)


class LoggingSettings(StrictModel):
    path: Path = Path("data/logs/app.jsonl")
    max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    backup_count: int = Field(default=5, ge=1)


class AppSettings(StrictModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    upload: UploadSettings = Field(default_factory=UploadSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    source_summary: dict[str, str] = Field(default_factory=dict)

    @field_validator("auth")
    @classmethod
    def require_credentials(cls, value: AuthSettings) -> AuthSettings:
        if not value.credentials and value.credentials_file is None:
            raise ValueError("credentials are required")
        return value


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"无法读取配置 {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"配置 {path.name} 必须是映射")
    return value


def load_credentials_file(path: Path) -> list[CredentialSettings]:
    value = _read_yaml_mapping(path)
    if set(value) != {"users"} or not isinstance(value["users"], list):
        raise ConfigError("credentials 文件只能包含 users 列表")
    try:
        credentials = [CredentialSettings.model_validate(item) for item in value["users"]]
    except ValidationError as exc:
        raise ConfigError(f"credentials 无效: {exc}") from exc
    if not credentials:
        raise ConfigError("credentials 不能为空")
    usernames = [item.username for item in credentials]
    if len(usernames) != len(set(usernames)):
        raise ConfigError("credentials 用户名不能重复")
    return credentials


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _ensure_data_root(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise ConfigError(f"data root 不可写: {exc}") from exc


def _env_overrides(env: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    known = {
        "RAI_DATA_ROOT",
        "RAI_CREDENTIALS_FILE",
        "RAI_CREDENTIALS_YAML",
        "RAI_SERVER_BIND_HOST",
        "RAI_SERVER_PUBLIC_ORIGIN",
        "RAI_SERVER_HTTPS",
        "RAI_UPLOAD_MAX_BYTES",
        "RAI_UPLOAD_MAX_PIXELS",
        "RAI_UPLOAD_TTL_SECONDS",
        "RAI_REQUIRED_MODELS",
        "RAI_LOG_FILE",
        "RAI_CONFIG_PATH",
        "RAI_INSTANCE_CONFIG_PATH",
    }
    unknown = sorted(key for key in env if key.startswith("RAI_") and key not in known)
    if unknown:
        raise ConfigError(f"未知环境变量配置: {', '.join(unknown)}")

    overrides: dict[str, Any] = {}
    sources: dict[str, str] = {}

    def set_value(section: str, key: str, env_key: str, parser: Any = str) -> None:
        if env_key not in env:
            return
        overrides.setdefault(section, {})[key] = parser(env[env_key])
        sources[f"{section}.{key}"] = f"env:{env_key}"

    set_value("data", "root", "RAI_DATA_ROOT")
    set_value("auth", "credentials_file", "RAI_CREDENTIALS_FILE")
    set_value("server", "bind_host", "RAI_SERVER_BIND_HOST")
    set_value("server", "public_origin", "RAI_SERVER_PUBLIC_ORIGIN")
    set_value("server", "https", "RAI_SERVER_HTTPS", lambda value: value.lower() == "true")
    set_value("upload", "max_bytes", "RAI_UPLOAD_MAX_BYTES", int)
    set_value("upload", "max_pixels", "RAI_UPLOAD_MAX_PIXELS", int)
    set_value("upload", "ttl_seconds", "RAI_UPLOAD_TTL_SECONDS", int)
    set_value("logging", "path", "RAI_LOG_FILE")
    if "RAI_REQUIRED_MODELS" in env:
        overrides.setdefault("models", {})["required_paths"] = [
            item for item in env["RAI_REQUIRED_MODELS"].split(os.pathsep) if item
        ]
        sources["models.required_paths"] = "env:RAI_REQUIRED_MODELS"
    if "RAI_CREDENTIALS_YAML" in env:
        try:
            value = yaml.safe_load(env["RAI_CREDENTIALS_YAML"])
            users = value["users"]
        except (KeyError, TypeError, yaml.YAMLError) as exc:
            raise ConfigError("RAI_CREDENTIALS_YAML 必须包含 users 列表") from exc
        overrides["auth"] = {"credentials": users, "source": "env"}
        sources["auth.credentials"] = "env:RAI_CREDENTIALS_YAML"
    return overrides, sources


def load_settings(
    *,
    global_path: Path | None = None,
    instance_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AppSettings:
    environment = dict(os.environ if env is None else env)
    data: dict[str, Any] = {}
    source_summary: dict[str, str] = {}

    if global_path is not None:
        data = _deep_merge(data, _read_yaml_mapping(global_path))
        source_summary["global"] = global_path.name
    if instance_path is not None:
        instance = _read_yaml_mapping(instance_path)
        forbidden = sorted(set(instance) & {"auth", "data", "server", "logging"})
        if forbidden:
            raise ConfigError(f"instance 配置禁止覆盖: {', '.join(forbidden)}")
        data = _deep_merge(data, instance)
        source_summary["instance"] = instance_path.name

    env_data, env_sources = _env_overrides(environment)
    data = _deep_merge(data, env_data)
    source_summary.update(env_sources)
    data["source_summary"] = source_summary

    try:
        settings = AppSettings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc

    auth = settings.auth
    if auth.credentials_file is not None:
        credentials = load_credentials_file(auth.credentials_file)
        auth = auth.model_copy(update={"credentials": credentials, "source": "file"})
        settings = settings.model_copy(update={"auth": auth})
    if not settings.auth.credentials:
        raise ConfigError("credentials 不能为空")
    if not _is_loopback(settings.server.bind_host) and not settings.server.https:
        raise ConfigError("非 loopback 监听必须启用 HTTPS")
    _ensure_data_root(settings.data.root)
    return settings


def load_settings_from_environment() -> AppSettings:
    global_path = os.environ.get("RAI_CONFIG_PATH")
    instance_path = os.environ.get("RAI_INSTANCE_CONFIG_PATH")
    return load_settings(
        global_path=Path(global_path) if global_path else None,
        instance_path=Path(instance_path) if instance_path else None,
    )
