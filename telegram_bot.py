"""
Telegram Bot — 投資決策輔助系統（繁體中文介面）
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import notion_db as nc
from data_fetcher import get_stock_info
from decision_engine import evaluate
from behavior_analysis import analyze_behavior
from logger import get_logger

log = get_logger(__name__)

TREND_EMOJI = {"UP": "📈", "DOWN": "📉", "SIDEWAYS": "➡️"}
RISK_EMOJI  = {"low": "🟢", "medium": "🟡", "high": "🔴"}
ACTION_EMOJI = {"BUY": "✅", "SELL": "🚨", "HOLD": "🔒", "WAIT": "⏳"}


def _fmt(p) -> str:
    if p is None:
        return "N/A"
    return f"{float(p):,.2f}"

def _sign(v) -> str:
    if v is None:
        return ""
    return f"▲ +{v:.2f}%" if v >= 0 else f"▼ {v:.2f}%"

async def _reply(update: Update, text: str) -> None:
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "投資人"
    await _reply(update, (
        f"👋 *你好，{name}！*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"歡迎使用 *投資決策輔助系統*\n\n"
        f"📊 我可以幫你：\n"
        f"  • 查詢股價與技術分析\n"
        f"  • 記錄買賣交易\n"
        f"  • 設定價格警報\n"
        f"  • 分析你的投資行為偏誤\n"
        f"  • 每日自動推送投資摘要\n\n"
        f"輸入 /help 查看所有指令 🚀"
    ))


# ──────────────────────────────────────────────────────────────────────────────
# /help
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, (
        "📖 *指令說明*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *查詢分析*\n"
        "`/stock 代號` — 即時股價 + 趨勢分析\n"
        "`/analyze 代號` — 完整 AI 決策報告\n\n"
        "💼 *交易紀錄*\n"
        "`/buy 代號 價格` — 記錄買入\n"
        "`/sell 代號 價格` — 記錄賣出\n\n"
        "🔔 *警報管理*\n"
        "`/alert 代號 目標價` — 設定價格警報\n\n"
        "📋 *帳戶總覽*\n"
        "`/portfolio` — 持倉損益\n"
        "`/behavior` — 行為偏誤分析\n"
        "`/summary` — 今日市場摘要\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 台股直接輸入代號即可，例如 `2330`\n"
        "💡 美股輸入英文代號，例如 `AAPL`"
    ))


# ──────────────────────────────────────────────────────────────────────────────
# /stock
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await _reply(update, "⚠️ 請輸入股票代號\n範例：`/stock 2330` 或 `/stock AAPL`")
        return

    symbol = ctx.args[0].upper()
    await update.message.reply_text(f"🔍 查詢 *{symbol}* 中，請稍候...", parse_mode=ParseMode.MARKDOWN)

    info     = await asyncio.to_thread(get_stock_info, symbol)
    analysis = await asyncio.to_thread(evaluate, symbol)

    price    = _fmt(info.get("price"))
    currency = info.get("currency", "")
    change   = _sign(info.get("change_pct"))
    trend    = analysis.get("trend", "N/A")
    rsi      = analysis.get("rsi14")
    rsi_str  = f"{rsi:.1f}" if rsi else "N/A"
    suggest  = analysis.get("suggestion", "N/A")
    risk     = analysis.get("risk_level", "N/A")
    rationale = analysis.get("technical", {}).get("rationale", "")

    t_emoji = TREND_EMOJI.get(trend, "")
    r_emoji = RISK_EMOJI.get(risk, "")
    a_emoji = ACTION_EMOJI.get(suggest, "")

    ma20 = analysis.get("technical", {}).get("ma20")
    ma50 = analysis.get("technical", {}).get("ma50")

    msg = (
        f"📊 *{symbol}* 即時分析\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *價格：* `{price} {currency}`\n"
        f"📉 *漲跌：* {change if change else 'N/A'}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *技術指標*\n"
        f"  趨勢：{t_emoji} `{trend}`\n"
        f"  MA20：`{_fmt(ma20)}`\n"
        f"  MA50：`{_fmt(ma50)}`\n"
        f"  RSI14：`{rsi_str}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 *AI 建議：* {a_emoji} `{suggest}`\n"
        f"⚠️ *風險等級：* {r_emoji} `{risk.upper()}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_{rationale}_"
    )
    await _reply(update, msg)


# ──────────────────────────────────────────────────────────────────────────────
# /analyze
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await _reply(update, "⚠️ 請輸入股票代號\n範例：`/analyze TSLA`")
        return

    symbol = ctx.args[0].upper()
    await update.message.reply_text(f"🧠 正在對 *{symbol}* 進行深度分析...", parse_mode=ParseMode.MARKDOWN)

    trades = await asyncio.to_thread(nc.get_trades, 50)
    result = await asyncio.to_thread(evaluate, symbol, trades)

    suggest  = result.get("suggestion", "N/A")
    risk     = result.get("risk_level", "N/A")
    conf     = result.get("confidence", 0)
    flags    = result.get("risk_flags", [])
    explain  = result.get("explanation", "")

    a_emoji = ACTION_EMOJI.get(suggest, "")
    r_emoji = RISK_EMOJI.get(risk, "")
    bar     = "█" * (conf // 10) + "░" * (10 - conf // 10)

    flags_str = "\n".join(f"  ⚡ `{f}`" for f in flags) if flags else "  ✅ 無異常風險訊號"

    msg = (
        f"🧠 *{symbol}* 完整決策報告\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *建議操作：* {a_emoji} `{suggest}`\n"
        f"⚠️ *風險等級：* {r_emoji} `{risk.upper()}`\n"
        f"🎯 *信心指數：* `{conf}/100`\n"
        f"  `{bar}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚩 *風險訊號*\n{flags_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 *分析依據*\n"
        f"```\n{explain}\n```"
    )
    await _reply(update, msg)

    await asyncio.to_thread(
        nc.log_decision,
        f"{symbol} → {suggest}",
        explain[:1800],
    )


# ──────────────────────────────────────────────────────────────────────────────
# /buy  /sell
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await _reply(update, "⚠️ 格式錯誤\n範例：`/buy AAPL 185.50`")
        return
    symbol = ctx.args[0].upper()
    try:
        price = float(ctx.args[1])
    except ValueError:
        await _reply(update, "❌ 價格格式錯誤，請輸入數字")
        return

    ok = await asyncio.to_thread(nc.log_trade, symbol, "buy", price)
    if ok:
        await _reply(update, (
            f"✅ *買入紀錄已儲存*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 股票：`{symbol}`\n"
            f"💰 買入價：`{_fmt(price)}`\n"
            f"📅 日期：`{datetime.now().strftime('%Y-%m-%d')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✍️ 已記錄至 Notion 交易日誌"
        ))
    else:
        await _reply(update, "❌ 儲存失敗，請確認 Notion 設定是否正確")


async def cmd_sell(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await _reply(update, "⚠️ 格式錯誤\n範例：`/sell AAPL 200.00`")
        return
    symbol = ctx.args[0].upper()
    try:
        price = float(ctx.args[1])
    except ValueError:
        await _reply(update, "❌ 價格格式錯誤，請輸入數字")
        return

    ok = await asyncio.to_thread(nc.log_trade, symbol, "sell", price)
    if ok:
        await _reply(update, (
            f"🚨 *賣出紀錄已儲存*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 股票：`{symbol}`\n"
            f"💰 賣出價：`{_fmt(price)}`\n"
            f"📅 日期：`{datetime.now().strftime('%Y-%m-%d')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✍️ 已記錄至 Notion 交易日誌"
        ))
    else:
        await _reply(update, "❌ 儲存失敗，請確認 Notion 設定是否正確")


# ──────────────────────────────────────────────────────────────────────────────
# /alert
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await _reply(update, "⚠️ 格式錯誤\n範例：`/alert 2330 900`")
        return
    symbol = ctx.args[0].upper()
    try:
        target = float(ctx.args[1])
    except ValueError:
        await _reply(update, "❌ 目標價格格式錯誤")
        return

    ok = await asyncio.to_thread(nc.add_watchlist, symbol, target, "above")
    if ok:
        await _reply(update, (
            f"🔔 *價格警報已設定*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 股票：`{symbol}`\n"
            f"🎯 目標價：`{_fmt(target)}`\n"
            f"📋 條件：突破目標價時通知\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ 每日排程自動檢查"
        ))
    else:
        await _reply(update, "❌ 警報設定失敗，請確認 Notion 設定")


# ──────────────────────────────────────────────────────────────────────────────
# /portfolio
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    holdings = await asyncio.to_thread(nc.get_portfolio)
    if not holdings:
        await _reply(update, (
            "📭 *持倉為空*\n\n"
            "使用 `/buy 代號 價格` 開始記錄你的第一筆交易"
        ))
        return

    lines = ["💼 *持倉總覽*", "━━━━━━━━━━━━━━━━━━━━"]
    total_value = 0.0
    total_cost  = 0.0

    for h in holdings:
        stock  = h.get("stock", "?")
        shares = h.get("shares") or 0
        cost   = h.get("cost") or 0
        cur    = h.get("current_price") or 0

        pos_value = shares * cur
        pos_cost  = shares * cost
        pnl       = pos_value - pos_cost
        pnl_pct   = (pnl / pos_cost * 100) if pos_cost else 0
        total_value += pos_value
        total_cost  += pos_cost

        emoji = "📈" if pnl >= 0 else "📉"
        sign  = "+" if pnl >= 0 else ""
        lines.append(
            f"{emoji} *{stock}*\n"
            f"  持股：`{shares}` 股 ｜ 成本：`{_fmt(cost)}`\n"
            f"  現價：`{_fmt(cur)}` ｜ 損益：`{sign}{pnl:.2f}` ({sign}{pnl_pct:.1f}%)"
        )

    total_pnl     = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
    sign = "+" if total_pnl >= 0 else ""
    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 *總損益：* `{sign}{total_pnl:.2f}` ({sign}{total_pnl_pct:.1f}%)",
        f"💵 *總市值：* `{_fmt(total_value)}`",
    ]
    await _reply(update, "\n".join(lines))


# ──────────────────────────────────────────────────────────────────────────────
# /behavior
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_behavior(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    trades = await asyncio.to_thread(nc.get_trades, 100)
    result = analyze_behavior(trades)

    patterns = result.get("patterns", [])
    insight  = result.get("insight", "")
    total    = result.get("total_trades", 0)
    recent   = result.get("recent_trades_30d", 0)
    fear     = result.get("fear_trades", 0)
    greed    = result.get("greed_trades", 0)

    pattern_lines = "\n".join(f"  ⚡ `{p}`" for p in patterns) if patterns else "  ✅ 未發現明顯偏誤"

    await _reply(update, (
        f"🧠 *行為偏誤分析報告*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *交易統計*\n"
        f"  總交易次數：`{total}` 筆\n"
        f"  近 30 天：`{recent}` 筆\n"
        f"  恐懼標記：`{fear}` 筆 😨\n"
        f"  貪婪標記：`{greed}` 筆 🤑\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚩 *偵測到的行為模式*\n{pattern_lines}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *洞察建議*\n_{insight}_"
    ))


# ──────────────────────────────────────────────────────────────────────────────
# /summary
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📊 正在生成今日市場摘要，請稍候...", parse_mode=ParseMode.MARKDOWN)
    summary = await asyncio.to_thread(_build_daily_summary)
    await _reply(update, summary)


# ──────────────────────────────────────────────────────────────────────────────
# Daily summary builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_daily_summary() -> str:
    from data_fetcher import get_current_price

    today    = datetime.now().strftime("%Y-%m-%d")
    weekday  = ["一", "二", "三", "四", "五", "六", "日"][datetime.now().weekday()]
    holdings = nc.get_portfolio()

    lines = [
        f"📅 *每日投資摘要*",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🗓 {today}（星期{weekday}）",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]

    if not holdings:
        lines.append("📭 目前無持倉")
    else:
        lines.append("💼 *持倉動態*")
        for h in holdings:
            stock = h.get("stock", "?")
            cost  = h.get("cost") or 0
            cur   = get_current_price(stock)
            if cur:
                nc.update_portfolio_price(stock, cur)
                pnl_pct = ((cur - cost) / cost * 100) if cost else 0
                emoji = "📈" if pnl_pct >= 0 else "📉"
                sign  = "+" if pnl_pct >= 0 else ""
                lines.append(f"  {emoji} `{stock}` {_fmt(cur)} ({sign}{pnl_pct:.1f}%)")
            else:
                lines.append(f"  ⚠️ `{stock}` 無法取得價格")

    # Watchlist alerts
    watchlist = nc.get_active_watchlist()
    triggered = []
    for entry in watchlist:
        stock     = entry["stock"]
        target    = entry["target_price"]
        condition = entry.get("condition", "above")
        cur       = get_current_price(stock)
        if cur is None or target is None:
            continue
        if (condition == "above" and cur >= target) or (condition == "below" and cur <= target):
            triggered.append(f"  🔔 `{stock}` 已達目標價 `{_fmt(target)}`（現價 `{_fmt(cur)}`）")
            nc.update_watchlist_status(entry["id"], "triggered")

    if triggered:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("🚨 *價格警報觸發*")
        lines.extend(triggered)

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        "💡 輸入 `/stock 代號` 查詢個股分析",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# App bootstrap
# ──────────────────────────────────────────────────────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("stock",    cmd_stock))
    app.add_handler(CommandHandler("analyze",  cmd_analyze))
    app.add_handler(CommandHandler("buy",      cmd_buy))
    app.add_handler(CommandHandler("sell",     cmd_sell))
    app.add_handler(CommandHandler("alert",    cmd_alert))
    app.add_handler(CommandHandler("portfolio",cmd_portfolio))
    app.add_handler(CommandHandler("behavior", cmd_behavior))
    app.add_handler(CommandHandler("summary",  cmd_summary))
    return app


if __name__ == "__main__":
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN 未設定，請複製 .env.example 為 .env 並填入值")
    log.info("啟動 Telegram Bot...")
    build_app().run_polling(drop_pending_updates=True)
