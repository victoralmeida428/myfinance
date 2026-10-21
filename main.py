"""Application entrypoint: `uvicorn main:app`."""

from myfinance.presentation.app import create_app

app = create_app()
