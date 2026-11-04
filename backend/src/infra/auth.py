from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from core.config import AuthSettings, ConfigError, load_credentials_file
from core.errors import app_error


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=actual_salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt$16384$8$1${actual_salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected_bytes = bytes.fromhex(expected)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected_bytes),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected_bytes)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    auth_method: str = "basic"


class CredentialStore:
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings
        credentials = settings.credentials
        if not credentials and settings.credentials_file is not None:
            credentials = load_credentials_file(settings.credentials_file)
        self._credentials = {item.username: item for item in credentials}

    def authenticate(self, username: str, password: str) -> Principal | None:
        credential = self._credentials.get(username)
        if credential is None or not verify_password(password, credential.password_hash):
            return None
        expires_at = credential.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= datetime.now(UTC):
                return None
        return Principal(username=credential.username, role=credential.role)

    def reload(self) -> None:
        if self.settings.source != "file" or self.settings.credentials_file is None:
            raise app_error("AUTH_RESTART_REQUIRED")
        try:
            credentials = load_credentials_file(self.settings.credentials_file)
        except ConfigError as exc:
            raise app_error("AUTH_INVALID", cause=exc) from exc
        self._credentials = {item.username: item for item in credentials}


def decode_basic_header(value: str | None) -> tuple[str, str] | None:
    if not value or not value.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(value[6:], validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    if not username or not password:
        return None
    return username, password
