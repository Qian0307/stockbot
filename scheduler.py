"""
Daily scheduler — runs as a separate process alongside the Telegram bot,
or can be imported and started from main.py.

Tasks run at DAILY_REPORT_HOUR:DAILY_REPORT_MINUTE (local time):
  1. Fetch current prices for all portfolio stocks
  2. Update Notion portfolio prices
  3. Check watchlist alerts
  4. Generate and send daily summary via Telegram
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

import config
from telegram_bot import _build_daily_summary
from logger import get_logger

log = get_logger(__name__)


async def _send_telegram(bot: Bot, text: str) -> None:
    if not config.TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_CHAT_ID not set — cannot send scheduled message.")
        return
    await bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode="Markdown",
    )


async def daily_job(bot: Bot) -> None:
    log.info("Running daily summary job at %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    try:
        summary = await asyncio.to_thread(_build_daily_summary)
        await _send_telegram(bot, summary)
        log.info("Daily summary sent successfully.")
    except Exception as exc:
        log.error("Daily job failed: %s", exc)


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Create and start the APScheduler. Returns the scheduler instance."""
    scheduler = AsyncIOScheduler()
    trigger = CronTrigger(
        hour=config.DAILY_REPORT_HOUR,
        minute=config.DAILY_REPORT_MINUTE,
    )
    scheduler.add_job(
        daily_job,
        trigger=trigger,
        args=[bot],
        id="daily_summary",
        replace_existing=True,
    )
    scheduler.start()
    log.info(
        "Scheduler started — daily summary at %02d:%02d local time.",
        config.DAILY_REPORT_HOUR,
        config.DAILY_REPORT_MINUTE,
    )
    return scheduler


if __name__ == "__main__":
    # Run scheduler standalone (useful for testing or separate deployment)
    async def _main():
        if not config.TELEGRAM_BOT_TOKEN:
            raise SystemExit("TELEGRAM_BOT_TOKEN not set.")
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        scheduler = start_scheduler(bot)
        log.info("Scheduler running. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()

    asyncio.run(_main())
