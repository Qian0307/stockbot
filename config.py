import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_PORTFOLIO_DB_ID = os.getenv("NOTION_PORTFOLIO_DB_ID", "")
NOTION_TRADES_DB_ID = os.getenv("NOTION_TRADES_DB_ID", "")
NOTION_WATCHLIST_DB_ID = os.getenv("NOTION_WATCHLIST_DB_ID", "")
NOTION_DECISION_LOG_DB_ID = os.getenv("NOTION_DECISION_LOG_DB_ID", "")

DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "8"))
DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))

# yfinance lookback window for indicator calculation
INDICATOR_LOOKBACK_DAYS = 90
