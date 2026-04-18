"""
Fetches stock price data from Yahoo Finance.
Supports US tickers (AAPL) and Taiwan stocks (2330.TW).

Uses a custom requests Session with browser-like headers to avoid
cloud-IP blocks that Yahoo Finance applies to datacenter traffic.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

from config import INDICATOR_LOOKBACK_DAYS
from logger import get_logger

log = get_logger(__name__)

# Browser-like session — prevents Yahoo Finance from blocking cloud server IPs
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})


def _normalize_symbol(symbol: str) -> str:
    """Auto-append .TW for pure numeric Taiwan tickers."""
    s = symbol.strip().upper()
    if s.isdigit():
        return s + ".TW"
    return s


def _download_with_retry(sym: str, start: str, end: str, retries: int = 3) -> Optional[pd.DataFrame]:
    """Download with retry + exponential backoff."""
    for attempt in range(retries):
        try:
            df = yf.download(
                sym,
                start=start,
                end=end,
                progress=False,
                auto_adjust=True,
                session=_SESSION,
            )
            if not df.empty:
                return df
            log.warning("Empty data for %s (attempt %d/%d)", sym, attempt + 1, retries)
        except Exception as exc:
            log.warning("Download error for %s attempt %d: %s", sym, attempt + 1, exc)
        time.sleep(2 ** attempt)   # 1s, 2s, 4s
    return None


def fetch_history(symbol: str, days: int = INDICATOR_LOOKBACK_DAYS) -> Optional[pd.DataFrame]:
    """
    Download OHLCV history for *symbol* over the last *days* calendar days.
    Returns a DataFrame with columns [Open, High, Low, Close, Volume] or None on failure.
    """
    sym = _normalize_symbol(symbol)
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    df = _download_with_retry(sym, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if df is None:
        log.warning("No data returned for %s", sym)
        return None

    # yfinance ≥0.2.x returns MultiIndex columns for single ticker — flatten it
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index = pd.to_datetime(df.index)
    log.info("Fetched %d rows for %s", len(df), sym)
    return df


def get_current_price(symbol: str) -> Optional[float]:
    """Return the latest closing price for *symbol*."""
    df = fetch_history(symbol, days=7)
    if df is None or df.empty:
        return None
    price = float(df["Close"].iloc[-1])
    log.info("Current price for %s: %.4f", _normalize_symbol(symbol), price)
    return price


def get_stock_info(symbol: str) -> dict:
    """
    Return a summary dict with current price, day change, volume.
    Falls back to history-based price if fast_info is unavailable.
    """
    sym = _normalize_symbol(symbol)
    try:
        ticker = yf.Ticker(sym, session=_SESSION)
        info = ticker.fast_info
        current = float(info.last_price) if info.last_price else None
        prev_close = float(info.previous_close) if info.previous_close else None
        change_pct = None
        if current and prev_close and prev_close != 0:
            change_pct = round((current - prev_close) / prev_close * 100, 2)
        if current is None:
            raise ValueError("last_price is None")
        return {
            "symbol": sym,
            "price": current,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "volume": getattr(info, "three_month_average_volume", None),
            "currency": getattr(info, "currency", "USD"),
        }
    except Exception as exc:
        log.warning("fast_info failed for %s (%s), falling back to history", sym, exc)
        price = get_current_price(symbol)
        return {
            "symbol": sym,
            "price": price,
            "prev_close": None,
            "change_pct": None,
            "volume": None,
            "currency": "TWD" if sym.endswith(".TW") else "USD",
        }
