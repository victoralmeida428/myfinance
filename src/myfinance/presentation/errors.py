"""HTTP error handlers mapping application/domain errors to responses."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from myfinance.application.errors import ProviderError
from myfinance.domain.exceptions import InvalidClientUserId


def register_exception_handlers(app: FastAPI) -> None:
    """Map domain and provider errors to safe JSON responses."""

    @app.exception_handler(InvalidClientUserId)
    async def _handle_invalid_client_user_id(
        _request: Request, exc: InvalidClientUserId
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ProviderError)
    async def _handle_provider_error(
        _request: Request, exc: ProviderError
    ) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
