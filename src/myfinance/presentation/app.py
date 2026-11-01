"""FastAPI application factory."""

from fastapi import FastAPI

from myfinance.presentation.errors import register_exception_handlers
from myfinance.presentation.routers import connect, pluggy, system


def create_app() -> FastAPI:
    """Build the application with routers and error handlers wired in."""
    app = FastAPI(title="MyFinance")
    app.include_router(system.router)
    app.include_router(connect.router)
    app.include_router(pluggy.router)
    register_exception_handlers(app)
    return app
