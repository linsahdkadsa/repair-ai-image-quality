from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.dependencies import get_credential_store, get_principal, require_roles
from api.dto import ReloadData, ReloadEnvelope, SessionData, SessionEnvelope
from infra.auth import CredentialStore, Principal

router = APIRouter(prefix="/api/v1/session", tags=["session"])


@router.get("", response_model=SessionEnvelope)
def session(principal: Annotated[Principal, Depends(get_principal)]) -> SessionEnvelope:
    return SessionEnvelope(data=SessionData.from_principal(principal))


@router.post("/reload-credentials", response_model=ReloadEnvelope)
def reload_credentials(
    _: Annotated[Principal, Depends(require_roles("admin"))],
    store: Annotated[CredentialStore, Depends(get_credential_store)],
) -> ReloadEnvelope:
    store.reload()
    return ReloadEnvelope(data=ReloadData(reloaded=True))
