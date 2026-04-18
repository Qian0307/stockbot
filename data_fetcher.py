"""
Fetches stock price data from Yahoo Finance.
Supports US tickers (AAPL) and Taiwan stocks (2330.TW).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from config import INDICATOR_LOOKBACK_DAYS
from logger import get_logger

log = get_logger(__name__)


def _normalize_symbol(symbol: str) -> str:
    """Auto-append .TW for pure numeric Taiwan tickers."""
    s = symbol.strip().upper()
    if s.isdigit():
        return s + ".TW"
    return s


def fetch_history(symbol: str, days: int = INDICATOR_LOOKBACK_DAYS) -> Optional[pd.DataFrame]:
    """
    Download OHLCV history for *symbol* over the last *days* calendar days.
    Returns a DataFrame with columns [Open, High, Low, Close, Volume] or None on failure.
    """
    sym = _normalize_symbol(symbol)
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    try:
        df = yf.download(sym, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=True)
        if df.empty:
            log.warning("No data returned for %s", sym)
            return None
        # yfinance ≥0.2.x returns MultiIndex columns for single ticker — flatten it
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        log.info("Fetched %d rows for %s", len(df), sym)
        return df
    except Exception as exc:
        log.error("Failed to fetch %s: %s", sym, exc)
        return None


def get_current_price(symbol: str) -> Optional[float]:
    """Return the latest closing price for *symbol*."""
    df = fetch_history(symbol, days=5)
    if df is None or df.empty:
        return None
    price = float(df["Close"].iloc[-1])
    log.info("Current price for %s: %.4f", _normalize_symbol(symbol), price)
    return price


def get_stock_info(symbol: str) -> dict:
    """
    Return a summary dict with current price, day change, volume.
    Falls back gracefully if Yahoo Finance is unavailable.
    """
    sym = _normalize_symbol(symbol)
    try:
        ticker = yf.Ticker(sym)
        info = ticker.fast_info
        current = float(info.last_price) if info.last_price else None
        prev_close = float(info.previous_close) if info.previous_close else None
        change_pct = None
        if current and prev_close and prev_close != 0:
            change_pct = round((current - prev_close) / prev_close * 100, 2)
        return {
            "symbol": sym,
            "price": current,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "volume": getattr(info, "three_month_average_volume", None),
            "currency": getattr(info, "currency", "USD"),
        }
    except Exception as exc:
        log.error("get_stock_info failed for %s: %s", sym, exc)
        # Fallback: use history
        price = get_current_price(symbol)
        return {"symbol": sym, "price": price, "prev_close": None, "change_pct": None,
                "volume": None, "currency": "N/A"}
