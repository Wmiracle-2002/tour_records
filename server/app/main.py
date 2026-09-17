from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.travel import router as travel_router
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    current_settings = settings or get_settings()
    application = FastAPI(title=current_settings.app_name)
    application.state.settings = current_settings
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(travel_router, prefix="/api/v1")

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
        _request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
            }
            for error in exception.errors()
        ]
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

    return application


app = create_app()
