"""
Entry point — runs the Telegram bot + daily scheduler in the same process.
Usage:
    python main.py
"""
from __future__ import annotations

import asyncio

from telegram import Bot

import config
from telegram_bot import build_app
from scheduler import start_scheduler
from logger import get_logger

log = get_logger("main")


async def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is missing.\n"
            "Copy .env.example → .env and fill in your credentials."
        )

    app = build_app()
    bot: Bot = app.bot

    # Start the scheduler (runs in the same event loop)
    scheduler = start_scheduler(bot)

    log.info("Bot and scheduler started. Press Ctrl+C to stop.")
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        # Keep running until interrupted
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutting down...")
    finally:
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
