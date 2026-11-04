from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes.health import router as health_router
from api.routes.session import router as session_router
from api.routes.uploads import router as uploads_router
from core.config import AppSettings, load_settings_from_environment
from core.errors import AppError, app_error
from infra.auth import CredentialStore
from infra.logging import configure_logging
from infra.security import SecurityMiddleware
from infra.trace import TraceMiddleware, current_trace_id
from repo.artifact_repository import ArtifactRepository
from service.upload_service import UploadService


def error_response(error: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error_code": error.error_code,
            "message": error.message,
            "trace_id": current_trace_id(),
        },
    )


def create_app(settings: AppSettings | None = None) -> FastAPI:
    configured_settings = settings

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active = configured_settings or load_settings_from_environment()
        repository = ArtifactRepository(active.data.root)
        repository.acquire_instance_lock()
        try:
            application.state.settings = active
            application.state.credential_store = CredentialStore(active.auth)
            application.state.upload_service = UploadService(
                repository,
                max_bytes=active.upload.max_bytes,
                max_pixels=active.upload.max_pixels,
                ttl_seconds=active.upload.ttl_seconds,
            )
            application.state.log_diagnostics = configure_logging(active.logging)
            yield
        finally:
            repository.release_instance_lock()

    application = FastAPI(
        title="Repair AI Image API",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @application.exception_handler(AppError)
    async def handle_app_error(_: Request, error: AppError) -> JSONResponse:
        logging.getLogger("repair_ai_image").info(
            "request failed error_code=%s cause=%r", error.error_code, error.cause
        )
        return error_response(error)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(app_error("VALIDATION_ERROR", cause=error))

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code == 404:
            return error_response(app_error("NOT_FOUND", cause=error))
        return error_response(app_error("INTERNAL_ERROR", cause=error))

    application.include_router(health_router)
    application.include_router(session_router)
    application.include_router(uploads_router)

    middleware_settings = configured_settings.server if configured_settings else None
    application.add_middleware(SecurityMiddleware, settings=middleware_settings)
    application.add_middleware(TraceMiddleware)
    return application


app = create_app()
