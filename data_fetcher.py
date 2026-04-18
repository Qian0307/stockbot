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

# TWSE MIS real-time API
_TWSE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
# TWSE historical daily data API (returns one month per request)
_TWSE_HISTORY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
# Stooq CSV API — free, no key, works from cloud IPs
_STOOQ_URL = "https://stooq.com/q/d/l/"


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


# ── TWSE historical data (台股月歷史資料) ──────────────────────────────────

def _twse_history(symbol: str, months: int = 4) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV history from TWSE for the past *months* months.
    Each API call returns one month; we fetch and concatenate.
    Column mapping: 開盤價→Open, 最高價→High, 最低價→Low, 收盤價→Close, 成交股數→Volume
    """
    code = symbol.replace(".TW", "").replace(".TWO", "")
    frames = []
    today = datetime.utcnow()

    for i in range(months):
        # Walk backwards month by month
        target = today - timedelta(days=i * 31)
        date_str = target.strftime("%Y%m01")
        try:
            resp = requests.get(
                _TWSE_HISTORY_URL,
                params={"response": "json", "date": date_str, "stockNo": code},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()
            if data.get("stat") != "OK":
                continue
            rows = data.get("data", [])
            # columns: 日期 成交股數 成交金額 開盤價 最高價 最低價 收盤價 漲跌價差 成交筆數
            records = []
            for row in rows:
                try:
                    # Date is in ROC format: "113/04/18" → convert to Gregorian
                    roc_date = row[0]
                    parts = roc_date.split("/")
                    year = int(parts[0]) + 1911
                    date = datetime(year, int(parts[1]), int(parts[2]))
                    # Strip commas from numbers
                    def to_f(s):
                        return float(str(s).replace(",", ""))
                    records.append({
                        "Date": date,
                        "Open": to_f(row[3]),
                        "High": to_f(row[4]),
                        "Low": to_f(row[5]),
                        "Close": to_f(row[6]),
                        "Volume": to_f(row[1]),
                    })
                except Exception:
                    continue
            if records:
                frames.append(pd.DataFrame(records).set_index("Date"))
        except Exception as exc:
            log.warning("TWSE history fetch failed for %s month %s: %s", code, date_str, exc)

    if not frames:
        return None

    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated()]
    log.info("TWSE history: %d rows for %s", len(df), symbol)
    return df


# ── Stooq history for US stocks ────────────────────────────────────────────

def _stooq_history(symbol: str, days: int) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV from Stooq CSV API.
    Stooq ticker: TSLA → tsla.us
    """
    stooq_sym = symbol.lower().replace(".tw", "").replace(".two", "")
    if not _is_taiwan(symbol):
        stooq_sym = stooq_sym + ".us"

    end = datetime.utcnow()
    start = end - timedelta(days=days)

    try:
        resp = requests.get(
            _STOOQ_URL,
            params={
                "s": stooq_sym,
                "d1": start.strftime("%Y%m%d"),
                "d2": end.strftime("%Y%m%d"),
                "i": "d",
            },
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        text = resp.text.strip()
        log.info("Stooq raw response for %s (first 120 chars): %s", stooq_sym, text[:120])

        if resp.status_code != 200 or len(text) < 30 or text.startswith("<"):
            log.warning("Stooq returned invalid response for %s", stooq_sym)
            return None

        from io import StringIO
        df = pd.read_csv(StringIO(text), on_bad_lines="skip")

        # Normalise column names (Stooq uses Title Case)
        df.columns = [c.strip().title() for c in df.columns]
        if "Date" not in df.columns:
            log.warning("Stooq: no Date column for %s, columns=%s", stooq_sym, df.columns.tolist())
            return None

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).set_index("Date").sort_index()

        if df.empty:
            return None

        log.info("Stooq history: %d rows for %s", len(df), symbol)
        return df
    except Exception as exc:
        log.warning("Stooq fetch failed for %s: %s", symbol, exc)
        return None


def _yf_chart_api(symbol: str, days: int) -> Optional[pd.DataFrame]:
    """
    Direct call to Yahoo Finance v8 chart API — sometimes works when
    the yfinance library is blocked, because we control the exact headers.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        resp = requests.get(
            url,
            params={"interval": "1d", "range": f"{max(days // 30, 1)}mo"},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://finance.yahoo.com",
            },
            timeout=10,
        )
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        r = result[0]
        timestamps = r.get("timestamp", [])
        ohlcv = r.get("indicators", {}).get("quote", [{}])[0]
        adj_close = r.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])

        closes = adj_close if adj_close else ohlcv.get("close", [])
        df = pd.DataFrame({
            "Date": pd.to_datetime(timestamps, unit="s"),
            "Open":   ohlcv.get("open", []),
            "High":   ohlcv.get("high", []),
            "Low":    ohlcv.get("low", []),
            "Close":  closes,
            "Volume": ohlcv.get("volume", []),
        }).dropna(subset=["Close"]).set_index("Date").sort_index()

        log.info("YF chart API: %d rows for %s", len(df), symbol)
        return df if not df.empty else None
    except Exception as exc:
        log.warning("YF chart API failed for %s: %s", symbol, exc)
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
    Taiwan stocks: TWSE history API first, yfinance as secondary.
    US stocks: yfinance only.
    """
    sym = _normalize_symbol(symbol)

    # Taiwan stocks — use TWSE official historical API
    if _is_taiwan(sym):
        months_needed = max(4, days // 30 + 1)
        df = _twse_history(sym, months=months_needed)
        if df is not None and not df.empty:
            return df
        log.warning("TWSE history failed for %s, trying yfinance", sym)

    # US stocks: yfinance → Stooq → YF chart API
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    df = _download_with_retry(sym, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    if df is not None and not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        return df

    log.info("yfinance failed for %s, trying Stooq...", sym)
    df = _stooq_history(sym, days)
    if df is not None and not df.empty:
        return df

    log.info("Stooq failed for %s, trying YF chart API...", sym)
    df = _yf_chart_api(sym, days)
    if df is None:
        log.warning("No historical data returned for %s", sym)
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

    # ── US stocks: yfinance fast_info → Stooq fallback ──────────────────────
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
        log.warning("fast_info failed for %s (%s), trying Stooq", sym, exc)

    # Fallback chain: Stooq → YF chart API
    for fn in (_stooq_history, _yf_chart_api):
        df = fn(sym, 5)
        if df is not None and not df.empty:
            price = float(df["Close"].iloc[-1])
            prev  = float(df["Close"].iloc[-2]) if len(df) >= 2 else None
            change_pct = round((price - prev) / prev * 100, 2) if prev else None
            return {
                "symbol": sym, "price": price, "prev_close": prev,
                "change_pct": change_pct, "volume": None, "currency": "USD",
            }

    return {
        "symbol": sym, "price": None, "prev_close": None,
        "change_pct": None, "volume": None, "currency": "USD",
    }
