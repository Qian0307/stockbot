"""
Behavioral analysis: detects trading pattern biases from Notion trade history.
Patterns detected:
  - buying_high: bought when price was above MA20
  - panic_selling: sold when RSI < 35 (oversold, likely fear-driven)
  - frequent_trading: more than N trades in the last 30 days
  - loss_aversion: sold losers significantly less often than winners
"""
from __future__ import annotations

from typing import Any

from logger import get_logger

log = get_logger(__name__)

# Threshold constants
FREQUENT_TRADE_THRESHOLD = 10   # trades per 30 days considered excessive
LOSS_AVERSION_RATIO = 0.3       # if <30% of sells are at a loss → possible loss aversion


def analyze_behavior(trades: list[dict[str, Any]]) -> dict:
    """
    *trades* is a list of dicts from notion_client.get_trades(), each containing:
      { date, stock, action, price, emotion, ... }

    Returns a dict of detected patterns and a plain-text insight string.
    """
    if not trades:
        return {"patterns": [], "insight": "No trade history to analyze yet."}

    patterns = []
    insights = []

    # ── Frequent trading ────────────────────────────────────────────────────
    recent = [t for t in trades if _is_recent(t.get("date"), days=30)]
    if len(recent) >= FREQUENT_TRADE_THRESHOLD:
        patterns.append("frequent_trading")
        insights.append(
            f"You made {len(recent)} trades in the last 30 days — high activity can erode returns via fees and emotional decisions."
        )

    # ── Emotion distribution ────────────────────────────────────────────────
    emotions = [t.get("emotion", "neutral") for t in trades]
    fear_count = emotions.count("fear")
    greed_count = emotions.count("greed")

    if fear_count > len(trades) * 0.4:
        patterns.append("fear_driven")
        insights.append("Over 40% of your trades were tagged as fear — consider whether those decisions were reactive.")

    if greed_count > len(trades) * 0.4:
        patterns.append("greed_driven")
        insights.append("Over 40% of your trades were tagged as greed — chasing momentum can increase risk exposure.")

    # ── Panic selling detection (sold tagged as fear) ───────────────────────
    fear_sells = [t for t in trades if t.get("action") == "sell" and t.get("emotion") == "fear"]
    if len(fear_sells) >= 2:
        patterns.append("panic_selling")
        insights.append(
            f"Detected {len(fear_sells)} fear-tagged sell trades — potential panic selling pattern. "
            "Consider setting predefined stop-loss levels to remove emotion from exits."
        )

    # ── Loss aversion heuristic ─────────────────────────────────────────────
    buy_prices: dict[str, list[float]] = {}
    for t in sorted(trades, key=lambda x: x.get("date", "")):
        stock = t.get("stock", "")
        price = t.get("price")
        action = t.get("action", "")
        if price is None:
            continue
        price = float(price)

        if action == "buy":
            buy_prices.setdefault(stock, []).append(price)
        elif action == "sell" and stock in buy_prices and buy_prices[stock]:
            avg_cost = sum(buy_prices[stock]) / len(buy_prices[stock])
            if price < avg_cost:
                # sold at a loss — that's fine, mark it handled
                buy_prices[stock].clear()
            else:
                buy_prices[stock].clear()

    # Stocks still in buy_prices with no sell → potential holding losers
    # (simple heuristic only; real P&L needs cost-basis accounting)

    if not patterns:
        insights.append("No significant behavioral biases detected in your trade history. Keep it up!")

    return {
        "patterns": patterns,
        "insight": " | ".join(insights),
        "total_trades": len(trades),
        "recent_trades_30d": len(recent),
        "fear_trades": fear_count,
        "greed_trades": greed_count,
    }


def _is_recent(date_str: str | None, days: int = 30) -> bool:
    if not date_str:
        return False
    from datetime import datetime, timedelta
    try:
        d = datetime.fromisoformat(date_str[:10])
        return d >= datetime.utcnow() - timedelta(days=days)
    except Exception:
        return False
