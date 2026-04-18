"""
Technical indicators: MA20, MA50, RSI.
Trend classification: UP / DOWN / SIDEWAYS.
All functions are pure (no side effects) and work on pandas Series/DataFrames.
"""
from __future__ import annotations

from typing import Literal, Optional

import numpy as np
import pandas as pd

from data_fetcher import fetch_history
from logger import get_logger

log = get_logger(__name__)

Trend = Literal["UP", "DOWN", "SIDEWAYS"]


# ─── Indicator calculations ────────────────────────────────────────────────

def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ─── Trend classification ──────────────────────────────────────────────────

def classify_trend(close: pd.Series) -> Trend:
    """
    Simple rule-based trend:
    - Price > MA20 > MA50 → UP
    - Price < MA20 < MA50 → DOWN
    - Otherwise          → SIDEWAYS
    """
    if len(close) < 50:
        return "SIDEWAYS"
    ma20 = moving_average(close, 20).iloc[-1]
    ma50 = moving_average(close, 50).iloc[-1]
    price = close.iloc[-1]

    if pd.isna(ma20) or pd.isna(ma50):
        return "SIDEWAYS"

    if price > ma20 > ma50:
        return "UP"
    if price < ma20 < ma50:
        return "DOWN"
    return "SIDEWAYS"


# ─── Full analysis report for a symbol ────────────────────────────────────

def analyze_symbol(symbol: str) -> Optional[dict]:
    """
    Returns a dict with price, MA20, MA50, RSI14, trend, and a short AI-style rationale.
    Returns None if data cannot be fetched.
    """
    df = fetch_history(symbol)
    if df is None or len(df) < 20:
        log.warning("Insufficient data to analyze %s", symbol)
        return None

    close = df["Close"].squeeze()

    ma20_val = moving_average(close, 20).iloc[-1]
    ma50_val = moving_average(close, 50).iloc[-1] if len(close) >= 50 else None
    rsi_val = rsi(close).iloc[-1] if len(close) >= 14 else None
    trend = classify_trend(close)
    price = float(close.iloc[-1])

    rationale = _build_rationale(price, ma20_val, ma50_val, rsi_val, trend)

    result = {
        "symbol": symbol.upper(),
        "price": round(price, 4),
        "ma20": round(float(ma20_val), 4) if not pd.isna(ma20_val) else None,
        "ma50": round(float(ma50_val), 4) if ma50_val is not None and not pd.isna(ma50_val) else None,
        "rsi14": round(float(rsi_val), 2) if rsi_val is not None and not pd.isna(rsi_val) else None,
        "trend": trend,
        "rationale": rationale,
    }
    log.info("Analysis for %s: trend=%s rsi=%.1f", symbol, trend, rsi_val or 0)
    return result


def _build_rationale(price: float, ma20, ma50, rsi_val, trend: Trend) -> str:
    parts = []

    if trend == "UP":
        parts.append("Price is above both MA20 and MA50 — bullish momentum.")
    elif trend == "DOWN":
        parts.append("Price is below both MA20 and MA50 — bearish pressure.")
    else:
        parts.append("Price is between moving averages — no clear directional trend.")

    if rsi_val is not None:
        if rsi_val > 70:
            parts.append(f"RSI {rsi_val:.1f} signals overbought — caution on new longs.")
        elif rsi_val < 30:
            parts.append(f"RSI {rsi_val:.1f} signals oversold — potential reversal zone.")
        else:
            parts.append(f"RSI {rsi_val:.1f} is neutral.")

    return " ".join(parts)
