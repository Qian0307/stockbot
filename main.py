"""
Entry point — runs the Telegram bot + daily scheduler in the same process.
Usage:
    python main.py
"""
from __future__ import annotations

import asyncio
import time

from telegram import Bot
from telegram.error import Conflict

import config
from telegram_bot import build_app
from scheduler import start_scheduler
from logger import get_logger

log = get_logger("main")

# How long to wait after delete_webhook before starting polling.
# Telegram's long-poll timeout is up to 50s, so 60s guarantees the old
# session has expired before we try to take over.
STARTUP_DELAY_SECONDS = 60


async def _clear_and_wait(bot: Bot) -> None:
    """Delete any existing webhook/polling session, then wait for it to expire."""
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Webhook cleared. Waiting %ds for old polling session to expire...",
                 STARTUP_DELAY_SECONDS)
    except Exception as exc:
        log.warning("delete_webhook failed (non-fatal): %s", exc)
    await asyncio.sleep(STARTUP_DELAY_SECONDS)


async def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is missing.\n"
            "Copy .env.example → .env and fill in your credentials."
        )

    app = build_app()
    bot: Bot = app.bot

    await _clear_and_wait(bot)

    scheduler = start_scheduler(bot)
    log.info("Bot and scheduler started.")

    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(
            drop_pending_updates=True,
            error_callback=_on_polling_error,
        )
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down...")
    finally:
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


def _on_polling_error(error: Exception) -> None:
    if isinstance(error, Conflict):
        # Another instance still alive — back off and let it die naturally
        log.error("Conflict detected. Another instance is still running. Waiting 60s...")
        time.sleep(60)
    else:
        log.error("Polling error: %s", error)


if __name__ == "__main__":
    asyncio.run(main())
