"""
Decision Engine: combines technical indicators + behavioral context
to produce an explainable investment suggestion.

Output:
  - risk_level: low | medium | high
  - suggestion: BUY | SELL | HOLD | WAIT
  - confidence: 0–100 (rule-based score)
  - explanation: human-readable string
"""
from __future__ import annotations

from typing import Literal, Optional

from indicators import analyze_symbol
from behavior_analysis import analyze_behavior
from logger import get_logger

log = get_logger(__name__)

RiskLevel = Literal["low", "medium", "high"]
Suggestion = Literal["BUY", "SELL", "HOLD", "WAIT"]


def evaluate(symbol: str, trades: list[dict] | None = None) -> dict:
    """
    Runs full decision analysis for *symbol*.
    Optionally incorporates behavioral context from *trades*.
    """
    tech = analyze_symbol(symbol)
    if tech is None:
        return {
            "symbol": symbol,
            "risk_level": "high",
            "suggestion": "WAIT",
            "confidence": 0,
            "explanation": "Could not retrieve market data. Avoid trading until data is available.",
        }

    trend = tech["trend"]
    rsi = tech.get("rsi14")
    price = tech["price"]
    ma20 = tech.get("ma20")
    ma50 = tech.get("ma50")

    score = 0          # positive → bullish, negative → bearish
    risk_flags = []
    reasons = []

    # ── Trend scoring ────────────────────────────────────────────────────────
    if trend == "UP":
        score += 30
        reasons.append("Uptrend confirmed (price > MA20 > MA50).")
    elif trend == "DOWN":
        score -= 30
        risk_flags.append("downtrend")
        reasons.append("Downtrend active (price < MA20 < MA50).")
    else:
        reasons.append("No clear trend — sideways market.")

    # ── RSI scoring ──────────────────────────────────────────────────────────
    if rsi is not None:
        if rsi < 30:
            score += 20
            reasons.append(f"RSI {rsi:.1f}: oversold — potential bounce opportunity.")
        elif rsi > 70:
            score -= 20
            risk_flags.append("overbought")
            reasons.append(f"RSI {rsi:.1f}: overbought — elevated reversal risk.")
        else:
            reasons.append(f"RSI {rsi:.1f}: neutral zone.")

    # ── MA proximity risk ────────────────────────────────────────────────────
    if ma20 and price:
        dist_pct = abs(price - ma20) / ma20 * 100
        if dist_pct > 10:
            risk_flags.append("extended_from_ma20")
            reasons.append(f"Price is {dist_pct:.1f}% away from MA20 — elevated volatility risk.")

    # ── Behavioral penalty ────────────────────────────────────────────────────
    behavior_insight = ""
    if trades:
        behavior = analyze_behavior(trades)
        patterns = behavior.get("patterns", [])
        behavior_insight = behavior.get("insight", "")

        if "panic_selling" in patterns or "frequent_trading" in patterns:
            score -= 10
            risk_flags.append("behavioral_bias")
            reasons.append("Behavioral bias detected — consider if this trade is emotionally driven.")

    # ── Map score → suggestion & risk ────────────────────────────────────────
    suggestion: Suggestion
    if score >= 35:
        suggestion = "BUY"
    elif score >= 10:
        suggestion = "HOLD"
    elif score >= -10:
        suggestion = "WAIT"
    else:
        suggestion = "SELL"

    risk_level: RiskLevel
    n_flags = len(risk_flags)
    if n_flags == 0:
        risk_level = "low"
    elif n_flags == 1:
        risk_level = "medium"
    else:
        risk_level = "high"

    confidence = min(100, max(0, abs(score)))

    explanation = (
        f"[{suggestion}] Risk: {risk_level.upper()} | Confidence: {confidence}/100\n"
        + "\n".join(f"  • {r}" for r in reasons)
    )
    if behavior_insight:
        explanation += f"\nBehavioral note: {behavior_insight}"

    log.info("Decision for %s: %s risk=%s score=%d", symbol, suggestion, risk_level, score)

    return {
        "symbol": symbol.upper(),
        "trend": trend,
        "price": price,
        "rsi14": rsi,
        "risk_level": risk_level,
        "suggestion": suggestion,
        "confidence": confidence,
        "risk_flags": risk_flags,
        "explanation": explanation,
        "technical": tech,
    }
