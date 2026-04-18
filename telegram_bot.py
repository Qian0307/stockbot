"""
Telegram Bot — Investment Decision Support System.

Commands:
  /start           – welcome message
  /stock <sym>     – price + trend + AI analysis
  /buy <sym> <px>  – log a buy trade
  /sell <sym> <px> – log a sell trade
  /alert <sym> <px>– set a price alert (watchlist)
  /portfolio       – show current portfolio with P&L
  /analyze <sym>   – full decision engine report
  /behavior        – behavioral bias report
  /summary         – on-demand daily summary
  /help            – command list
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import config
import notion_db as nc
from data_fetcher import get_stock_info
from decision_engine import evaluate
from behavior_analysis import analyze_behavior
from logger import get_logger

log = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_price(p) -> str:
    if p is None:
        return "N/A"
    return f"{float(p):,.4f}"

def _sign(v) -> str:
    if v is None:
        return ""
    return f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"

async def _reply(update: Update, text: str) -> None:
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────────────────────
# Command handlers
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, (
        "*Investment Decision Support System*\n"
        "────────────────────────\n"
        "Use /help to see all available commands.\n"
        "Your trades and decisions are stored in Notion automatically."
    ))


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, (
        "*Available Commands*\n"
        "────────────────────────\n"
        "`/stock <SYMBOL>` — price + trend analysis\n"
        "`/analyze <SYMBOL>` — full AI decision report\n"
        "`/buy <SYMBOL> <PRICE>` — log a buy trade\n"
        "`/sell <SYMBOL> <PRICE>` — log a sell trade\n"
        "`/alert <SYMBOL> <PRICE>` — set price alert\n"
        "`/portfolio` — view holdings + P&L\n"
        "`/behavior` — behavioral bias analysis\n"
        "`/summary` — on-demand daily summary\n"
        "\nTaiwan stocks: use `2330` (auto-appends .TW)"
    ))


async def cmd_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await _reply(update, "Usage: `/stock <SYMBOL>`")
        return

    symbol = ctx.args[0].upper()
    await update.message.reply_text(f"Fetching data for *{symbol}*...", parse_mode=ParseMode.MARKDOWN)

    # Run blocking calls in a thread so we don't block the event loop
    info = await asyncio.to_thread(get_stock_info, symbol)
    analysis = await asyncio.to_thread(evaluate, symbol)

    price = _fmt_price(info.get("price"))
    change = _sign(info.get("change_pct"))
    trend = analysis.get("trend", "N/A")
    rsi = analysis.get("rsi14")
    rsi_str = f"{rsi:.1f}" if rsi else "N/A"
    suggestion = analysis.get("suggestion", "N/A")
    risk = analysis.get("risk_level", "N/A").upper()
    rationale = analysis.get("technical", {}).get("rationale", "")

    msg = (
        f"*{symbol}*\n"
        f"Price: `{price}` {info.get('currency', '')}  {change}\n"
        f"Trend: `{trend}` | RSI: `{rsi_str}`\n"
        f"────────────────────────\n"
        f"Decision: *{suggestion}* | Risk: *{risk}*\n"
        f"\n_{rationale}_"
    )
    await _reply(update, msg)


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await _reply(update, "Usage: `/analyze <SYMBOL>`")
        return

    symbol = ctx.args[0].upper()
    await update.message.reply_text(f"Running full analysis for *{symbol}*...", parse_mode=ParseMode.MARKDOWN)

    trades = await asyncio.to_thread(nc.get_trades, 50)
    result = await asyncio.to_thread(evaluate, symbol, trades)

    explanation = result.get("explanation", "No explanation available.")
    await _reply(update, f"```\n{explanation}\n```")

    # Log the decision to Notion
    await asyncio.to_thread(
        nc.log_decision,
        f"{symbol} → {result['suggestion']}",
        explanation[:1800],
    )


async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await _reply(update, "Usage: `/buy <SYMBOL> <PRICE>`\nExample: `/buy AAPL 185.50`")
        return

    symbol = ctx.args[0].upper()
    try:
        price = float(ctx.args[1])
    except ValueError:
        await _reply(update, "Invalid price. Use a number, e.g. `/buy AAPL 185.50`")
        return

    ok = await asyncio.to_thread(nc.log_trade, symbol, "buy", price, reason="", emotion="neutral")
    if ok:
        await _reply(update, f"Buy logged: *{symbol}* @ `{_fmt_price(price)}`\nRecord saved to Notion Trades.")
    else:
        await _reply(update, "Failed to save to Notion. Check your NOTION_TRADES_DB_ID and token.")


async def cmd_sell(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await _reply(update, "Usage: `/sell <SYMBOL> <PRICE>`\nExample: `/sell AAPL 200.00`")
        return

    symbol = ctx.args[0].upper()
    try:
        price = float(ctx.args[1])
    except ValueError:
        await _reply(update, "Invalid price. Use a number.")
        return

    ok = await asyncio.to_thread(nc.log_trade, symbol, "sell", price, reason="", emotion="neutral")
    if ok:
        await _reply(update, f"Sell logged: *{symbol}* @ `{_fmt_price(price)}`\nRecord saved to Notion Trades.")
    else:
        await _reply(update, "Failed to save to Notion.")


async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await _reply(update, "Usage: `/alert <SYMBOL> <TARGET_PRICE>`\nExample: `/alert 2330 900`")
        return

    symbol = ctx.args[0].upper()
    try:
        target = float(ctx.args[1])
    except ValueError:
        await _reply(update, "Invalid price.")
        return

    ok = await asyncio.to_thread(nc.add_watchlist, symbol, target, "above")
    if ok:
        await _reply(update,
            f"Alert set: notify when *{symbol}* crosses `{_fmt_price(target)}`\n"
            "The scheduler checks this daily."
        )
    else:
        await _reply(update, "Failed to save alert to Notion.")


async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    holdings = await asyncio.to_thread(nc.get_portfolio)
    if not holdings:
        await _reply(update, "Portfolio is empty. Use `/buy <SYM> <PRICE>` to add positions.")
        return

    lines = ["*Portfolio Summary*", "────────────────────────"]
    total_value = 0.0
    total_cost = 0.0

    for h in holdings:
        stock = h.get("stock", "?")
        shares = h.get("shares") or 0
        cost = h.get("cost") or 0
        cur = h.get("current_price") or 0

        position_value = shares * cur
        position_cost = shares * cost
        pnl = position_value - position_cost
        pnl_pct = (pnl / position_cost * 100) if position_cost else 0

        total_value += position_value
        total_cost += position_cost

        emoji = "▲" if pnl >= 0 else "▼"
        lines.append(
            f"{emoji} *{stock}*: {shares} shares @ `{_fmt_price(cost)}` cost\n"
            f"   Current: `{_fmt_price(cur)}` | P&L: `{pnl:+.2f}` ({pnl_pct:+.1f}%)"
        )

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
    lines.append("────────────────────────")
    lines.append(f"Total P&L: `{total_pnl:+.2f}` ({total_pnl_pct:+.1f}%)")

    await _reply(update, "\n".join(lines))


async def cmd_behavior(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    trades = await asyncio.to_thread(nc.get_trades, 100)
    result = analyze_behavior(trades)

    patterns = result.get("patterns", [])
    insight = result.get("insight", "")
    total = result.get("total_trades", 0)
    recent = result.get("recent_trades_30d", 0)

    pattern_str = ", ".join(patterns) if patterns else "none detected"
    msg = (
        f"*Behavioral Analysis*\n"
        f"────────────────────────\n"
        f"Total trades: `{total}` | Last 30d: `{recent}`\n"
        f"Patterns: `{pattern_str}`\n\n"
        f"_{insight}_"
    )
    await _reply(update, msg)


async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Generating daily summary...", parse_mode=ParseMode.MARKDOWN)
    summary = await asyncio.to_thread(_build_daily_summary)
    await _reply(update, summary)


# ──────────────────────────────────────────────────────────────────────────────
# Daily summary builder (also called by scheduler)
# ──────────────────────────────────────────────────────────────────────────────

def _build_daily_summary() -> str:
    """Synchronous summary builder — called via asyncio.to_thread."""
    from data_fetcher import get_current_price

    holdings = nc.get_portfolio()
    lines = [f"*Daily Market Summary* — {datetime.now().strftime('%Y-%m-%d')}",
             "────────────────────────"]

    if not holdings:
        lines.append("No portfolio positions found.")
    else:
        for h in holdings:
            stock = h.get("stock", "?")
            cur_price = get_current_price(stock)
            if cur_price:
                nc.update_portfolio_price(stock, cur_price)
                cost = h.get("cost") or 0
                shares = h.get("shares") or 0
                pnl_pct = ((cur_price - cost) / cost * 100) if cost else 0
                emoji = "▲" if pnl_pct >= 0 else "▼"
                lines.append(f"{emoji} {stock}: `{_fmt_price(cur_price)}` ({pnl_pct:+.1f}%)")

    # Check watchlist alerts
    watchlist = nc.get_active_watchlist()
    triggered = []
    for entry in watchlist:
        stock = entry["stock"]
        target = entry["target_price"]
        condition = entry.get("condition", "above")
        cur = get_current_price(stock)
        if cur is None or target is None:
            continue
        if (condition == "above" and cur >= target) or (condition == "below" and cur <= target):
            triggered.append(f"ALERT: {stock} hit `{_fmt_price(cur)}` (target {_fmt_price(target)})")
            nc.update_watchlist_status(entry["id"], "triggered")

    if triggered:
        lines.append("\n*Price Alerts Triggered*")
        lines.extend(triggered)

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Bot bootstrap
# ──────────────────────────────────────────────────────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("behavior", cmd_behavior))
    app.add_handler(CommandHandler("summary", cmd_summary))
    return app


if __name__ == "__main__":
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill in values.")
    log.info("Starting Telegram bot...")
    build_app().run_polling(drop_pending_updates=True)
