import asyncio
import json
import logging
import re
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent.runtime import AgentRuntime
from app.api.agent import router as agent_router
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.travel import router as travel_router
from app.core.config import Settings, get_settings
from app.core.request_context import request_context
from app.storage import ObjectStorage, create_storage


http_logger = logging.getLogger("footmarks.http")
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


def _request_id(value: str | None) -> str:
    return value if value is not None and _REQUEST_ID_PATTERN.fullmatch(value) else uuid4().hex


def _http_event(**fields: object) -> None:
    http_logger.info(json.dumps(fields, ensure_ascii=False, separators=(",", ":")))


def _configure_logging() -> None:
    """Make request and Agent diagnostics visible in the container logs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger("app.api.agent").setLevel(logging.INFO)
    logging.getLogger("footmarks.agent").setLevel(logging.INFO)


_configure_logging()


def create_app(
    settings: Settings | None = None,
    storage: ObjectStorage | None = None,
    agent_runtime: AgentRuntime | None = None,
) -> FastAPI:
    current_settings = settings or get_settings()
    application = FastAPI(title=current_settings.app_name)
    application.state.settings = current_settings
    application.state.storage = storage or create_storage(current_settings)
    application.state.agent_runtime = agent_runtime or AgentRuntime(current_settings)
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(travel_router, prefix="/api/v1")
    application.include_router(agent_router, prefix="/api/v1")

    @application.middleware("http")
    async def trace_request(request: Request, call_next):
        request_id = _request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        started_at = monotonic()
        status_code: int | None = None
        outcome = "cancelled"
        exception_type: str | None = None
        _http_event(event="http_request_started", request_id=request_id, method=request.method)
        with request_context(request_id):
            try:
                response = await call_next(request)
                status_code = response.status_code
                outcome = (
                    "server_error" if status_code >= 500 else
                    "client_error" if status_code >= 400 else "success"
                )
                response.headers["X-Request-ID"] = request_id
                return response
            except asyncio.CancelledError:
                raise
            except Exception as error:
                status_code = 500
                outcome = "server_error"
                exception_type = type(error).__name__
                http_logger.exception("Unhandled HTTP error request_id=%s", request_id)
                raise
            finally:
                route = request.scope.get("route")
                fields = {
                    "event": "http_request_completed",
                    "request_id": request_id,
                    "method": request.method,
                    "route": getattr(route, "path", "unmatched"),
                    "status_code": status_code,
                    "duration_ms": round((monotonic() - started_at) * 1000, 2),
                    "outcome": outcome,
                }
                if exception_type is not None:
                    fields["exception_type"] = exception_type
                _http_event(**fields)

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exception: StarletteHTTPException
    ) -> JSONResponse:
        if exception.status_code == 404:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "not_found",
                        "message": "Resource not found",
                    }
                },
            )
        return JSONResponse(
            status_code=exception.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "message": str(exception.detail),
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
            }
            for error in exception.errors()
        ]
        _http_event(
            event="http_validation_failed",
            request_id=request.state.request_id,
            fields=[detail["field"] for detail in details],
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": details,
                }
            },
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _exception: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
            headers={"X-Request-ID": request.state.request_id},
        )

    return application


app = create_app()
