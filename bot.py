"""Telegram bot entrypoint: `uv run python bot.py`."""

from myfinance.presentation.telegram.app import run_bot

if __name__ == "__main__":
    run_bot()
