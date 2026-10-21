"""Logging configuration must suppress libraries that log full request URLs."""

from __future__ import annotations

import logging

from myfinance.presentation.telegram.app import _configure_logging

_QUIET_LOGGERS = ("httpx", "httpcore", "httpx2", "openai")


def test_configure_logging_silences_http_client_loggers() -> None:
    _configure_logging()

    for name in _QUIET_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING
