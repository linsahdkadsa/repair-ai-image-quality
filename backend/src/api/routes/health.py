from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.dependencies import get_log_diagnostics, get_settings, require_roles
from api.dto import LoggingDiagnosticsData, SystemStatusData, SystemStatusEnvelope
from core.config import AppSettings
from infra.auth import Principal
from infra.logging import LogDiagnostics

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def ready(settings: Annotated[AppSettings, Depends(get_settings)]) -> JSONResponse:
    if any(not path.is_file() for path in settings.models.required_paths):
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "ready": False,
                "reason": "required_model_missing",
            },
        )
    return JSONResponse(content={"status": "ready", "ready": True})


@router.get("/api/v1/system/status", response_model=SystemStatusEnvelope, tags=["system"])
def system_status(
    _: Annotated[Principal, Depends(require_roles("admin"))],
    diagnostics: Annotated[LogDiagnostics, Depends(get_log_diagnostics)],
) -> SystemStatusEnvelope:
    return SystemStatusEnvelope(
        data=SystemStatusData(
            logging=LoggingDiagnosticsData(
                write_failures=diagnostics.write_failures,
                dropped_records=diagnostics.dropped_records,
            )
        )
    )
