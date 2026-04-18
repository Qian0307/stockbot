"""
Fetches stock price data.
- US stocks: Yahoo Finance (yfinance)
- Taiwan stocks (.TW): TWSE MIS API (即時) + Yahoo Finance (歷史)

Yahoo Finance blocks many cloud datacenter IPs, so Taiwan real-time prices
fall back to the Taiwan Stock Exchange's free public API.
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

# Browser-like session for yfinance
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

# TWSE MIS real-time API (no auth required, works from any IP)
_TWSE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


def _normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.isdigit():
        return s + ".TW"
    return s


def _is_taiwan(sym: str) -> bool:
    return sym.endswith(".TW") or sym.endswith(".TWO")


# ── TWSE real-time price (台股即時價格) ────────────────────────────────────

def _twse_price(symbol: str) -> Optional[dict]:
    """
    Fetch real-time price from TWSE MIS API.
    Works during trading hours (09:00–13:30 TW time) on weekdays.
    Returns dict with price, prev_close, change_pct or None on failure.
    """
    code = symbol.replace(".TW", "").replace(".TWO", "")
    # tse_ prefix for listed stocks; otc_ for OTC — try tse first
    ex_ch = f"tse_{code}.tw"
    try:
        resp = requests.get(
            _TWSE_URL,
            params={"ex_ch": ex_ch, "json": "1", "delay": "0"},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        data = resp.json()
        arr = data.get("msgArray", [])
        if not arr:
            # Try OTC (上櫃)
            ex_ch = f"otc_{code}.tw"
            resp = requests.get(
                _TWSE_URL,
                params={"ex_ch": ex_ch, "json": "1", "delay": "0"},
                timeout=8,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()
            arr = data.get("msgArray", [])

        if not arr:
            return None

        item = arr[0]
        price_str = item.get("z", "-")   # current price ("-" when market closed)
        prev_str = item.get("y", "-")    # yesterday close

        if price_str == "-" or not price_str:
            # Market closed — use yesterday's close as best available price
            price_str = prev_str

        if not price_str or price_str == "-":
            return None

        price = float(price_str)
        prev = float(prev_str) if prev_str and prev_str != "-" else None
        change_pct = round((price - prev) / prev * 100, 2) if prev else None

        return {
            "symbol": symbol,
            "price": price,
            "prev_close": prev,
            "change_pct": change_pct,
            "currency": "TWD",
            "source": "TWSE",
        }
    except Exception as exc:
        log.warning("TWSE API failed for %s: %s", symbol, exc)
        return None


# ── Yahoo Finance history (needed for MA / RSI) ────────────────────────────

def _download_with_retry(sym: str, start: str, end: str, retries: int = 3) -> Optional[pd.DataFrame]:
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
        time.sleep(2 ** attempt)
    return None


def fetch_history(symbol: str, days: int = INDICATOR_LOOKBACK_DAYS) -> Optional[pd.DataFrame]:
    """
    Download OHLCV history. Returns flattened DataFrame or None.
    For Taiwan stocks yfinance may fail from cloud IPs — callers should
    handle None gracefully (indicators will show N/A).
    """
    sym = _normalize_symbol(symbol)
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    df = _download_with_retry(sym, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if df is None:
        log.warning("No historical data returned for %s", sym)
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index = pd.to_datetime(df.index)
    log.info("Fetched %d rows for %s", len(df), sym)
    return df


def get_current_price(symbol: str) -> Optional[float]:
    sym = _normalize_symbol(symbol)

    # Taiwan stocks: try TWSE first (works from any IP)
    if _is_taiwan(sym):
        info = _twse_price(sym)
        if info and info.get("price"):
            return info["price"]

    # US stocks or TWSE fallback: use history
    df = fetch_history(symbol, days=7)
    if df is None or df.empty:
        return None
    return float(df["Close"].iloc[-1])


def get_stock_info(symbol: str) -> dict:
    """
    Return price summary dict.
    Taiwan stocks use TWSE API; US stocks use yfinance fast_info.
    """
    sym = _normalize_symbol(symbol)

    # ── Taiwan stocks ────────────────────────────────────────────────────────
    if _is_taiwan(sym):
        twse = _twse_price(sym)
        if twse:
            log.info("TWSE price for %s: %.2f", sym, twse["price"])
            return twse
        # TWSE failed (market closed + no data) — fallback to yfinance history
        log.warning("TWSE unavailable for %s, trying yfinance history", sym)
        price = get_current_price(symbol)
        return {
            "symbol": sym, "price": price, "prev_close": None,
            "change_pct": None, "volume": None, "currency": "TWD",
        }

    # ── US stocks ────────────────────────────────────────────────────────────
    try:
        ticker = yf.Ticker(sym, session=_SESSION)
        info = ticker.fast_info
        current = float(info.last_price) if info.last_price else None
        prev_close = float(info.previous_close) if info.previous_close else None
        if current is None:
            raise ValueError("last_price is None")
        change_pct = round((current - prev_close) / prev_close * 100, 2) if (current and prev_close) else None
        return {
            "symbol": sym, "price": current, "prev_close": prev_close,
            "change_pct": change_pct,
            "volume": getattr(info, "three_month_average_volume", None),
            "currency": getattr(info, "currency", "USD"),
        }
    except Exception as exc:
        log.warning("fast_info failed for %s (%s), falling back to history", sym, exc)
        price = get_current_price(symbol)
        return {
            "symbol": sym, "price": price, "prev_close": None,
            "change_pct": None, "volume": None, "currency": "USD",
        }
