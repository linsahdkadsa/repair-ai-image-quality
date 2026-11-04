from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from core.config import AppSettings
from core.errors import app_error
from infra.auth import CredentialStore, Principal, decode_basic_header
from infra.logging import LogDiagnostics
from service.upload_service import UploadService


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def get_credential_store(request: Request) -> CredentialStore:
    return request.app.state.credential_store


def get_upload_service(request: Request) -> UploadService:
    return request.app.state.upload_service


def get_log_diagnostics(request: Request) -> LogDiagnostics:
    return request.app.state.log_diagnostics


def get_principal(
    request: Request,
    store: Annotated[CredentialStore, Depends(get_credential_store)],
) -> Principal:
    authorization = request.headers.get("authorization")
    if authorization is None:
        raise app_error("AUTH_REQUIRED")
    credentials = decode_basic_header(authorization)
    if credentials is None:
        raise app_error("AUTH_INVALID")
    principal = store.authenticate(*credentials)
    if principal is None:
        raise app_error("AUTH_INVALID")
    return principal


def require_roles(*roles: str) -> Callable[..., Principal]:
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if principal.role not in roles:
            raise app_error("ROLE_FORBIDDEN")
        return principal

    return dependency
