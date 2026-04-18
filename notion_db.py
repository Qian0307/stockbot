"""
Notion API client for all 4 databases:
  1. Portfolio  – current holdings
  2. Trades     – buy/sell log
  3. Watchlist  – price alert targets
  4. Decision Log – AI decision history

Uses the official notion-client library (async-compatible via asyncio.to_thread).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from notion_client import Client as NotionSDKClient  # pip package, not this file

import config
from logger import get_logger

log = get_logger(__name__)

_client: Optional[NotionSDKClient] = None


def _get_client() -> NotionSDKClient:
    global _client
    if _client is None:
        if not config.NOTION_TOKEN:
            raise RuntimeError("NOTION_TOKEN is not set in environment.")
        _client = NotionSDKClient(auth=config.NOTION_TOKEN)
    return _client


# ──────────────────────────────────────────────────────────────────────────────
# Helper builders
# ──────────────────────────────────────────────────────────────────────────────

def _title(text: str) -> dict:
    return {"title": [{"text": {"content": str(text)}}]}

def _rich_text(text: str) -> dict:
    return {"rich_text": [{"text": {"content": str(text)}}]}

def _number(val: float | None) -> dict:
    return {"number": float(val) if val is not None else None}

def _select(val: str) -> dict:
    return {"select": {"name": str(val)}}

def _date(val: str) -> dict:
    return {"date": {"start": val}}

def _prop(page: dict, name: str) -> Any:
    """Extract raw property value from a Notion page object."""
    return page.get("properties", {}).get(name, {})

def _read_title(page: dict, name: str = "stock") -> str:
    t = _prop(page, name).get("title", [])
    return t[0]["plain_text"] if t else ""

def _read_number(page: dict, name: str) -> Optional[float]:
    return _prop(page, name).get("number")

def _read_rich_text(page: dict, name: str) -> str:
    rt = _prop(page, name).get("rich_text", [])
    return rt[0]["plain_text"] if rt else ""

def _read_select(page: dict, name: str) -> str:
    sel = _prop(page, name).get("select")
    return sel["name"] if sel else ""

def _read_date(page: dict, name: str) -> str:
    d = _prop(page, name).get("date")
    return d["start"] if d else ""


# ──────────────────────────────────────────────────────────────────────────────
# Portfolio
# ──────────────────────────────────────────────────────────────────────────────

def get_portfolio() -> list[dict]:
    """Return all portfolio holdings."""
    nc = _get_client()
    try:
        res = nc.databases.query(database_id=config.NOTION_PORTFOLIO_DB_ID)
        rows = []
        for page in res.get("results", []):
            rows.append({
                "id": page["id"],
                "stock": _read_title(page, "stock"),
                "cost": _read_number(page, "cost"),
                "shares": _read_number(page, "shares"),
                "current_price": _read_number(page, "current_price"),
            })
        return rows
    except Exception as exc:
        log.error("get_portfolio failed: %s", exc)
        return []


def upsert_portfolio(stock: str, cost: float, shares: float, current_price: float) -> bool:
    """Create or update a portfolio entry (matched by stock ticker)."""
    nc = _get_client()
    try:
        res = nc.databases.query(
            database_id=config.NOTION_PORTFOLIO_DB_ID,
            filter={"property": "stock", "title": {"equals": stock.upper()}},
        )
        props = {
            "stock": _title(stock.upper()),
            "cost": _number(cost),
            "shares": _number(shares),
            "current_price": _number(current_price),
        }
        if res["results"]:
            page_id = res["results"][0]["id"]
            nc.pages.update(page_id=page_id, properties=props)
            log.info("Updated portfolio entry for %s", stock)
        else:
            nc.pages.create(parent={"database_id": config.NOTION_PORTFOLIO_DB_ID}, properties=props)
            log.info("Created portfolio entry for %s", stock)
        return True
    except Exception as exc:
        log.error("upsert_portfolio failed for %s: %s", stock, exc)
        return False


def update_portfolio_price(stock: str, current_price: float) -> bool:
    """Lightweight price-only update."""
    nc = _get_client()
    try:
        res = nc.databases.query(
            database_id=config.NOTION_PORTFOLIO_DB_ID,
            filter={"property": "stock", "title": {"equals": stock.upper()}},
        )
        if not res["results"]:
            return False
        page_id = res["results"][0]["id"]
        nc.pages.update(page_id=page_id, properties={"current_price": _number(current_price)})
        return True
    except Exception as exc:
        log.error("update_portfolio_price failed for %s: %s", stock, exc)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Trades
# ──────────────────────────────────────────────────────────────────────────────

def log_trade(stock: str, action: str, price: float, reason: str = "", emotion: str = "neutral") -> bool:
    """Append a trade record to the Trades database."""
    nc = _get_client()
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        nc.pages.create(
            parent={"database_id": config.NOTION_TRADES_DB_ID},
            properties={
                "date": _date(today),
                "stock": _title(stock.upper()),
                "action": _select(action.lower()),
                "price": _number(price),
                "reason": _rich_text(reason),
                "emotion": _select(emotion.lower()),
            },
        )
        log.info("Logged %s trade for %s @ %.4f", action, stock, price)
        return True
    except Exception as exc:
        log.error("log_trade failed: %s", exc)
        return False


def get_trades(limit: int = 50) -> list[dict]:
    """Return the most recent *limit* trades."""
    nc = _get_client()
    try:
        res = nc.databases.query(
            database_id=config.NOTION_TRADES_DB_ID,
            sorts=[{"property": "date", "direction": "descending"}],
            page_size=min(limit, 100),
        )
        rows = []
        for page in res.get("results", []):
            rows.append({
                "id": page["id"],
                "date": _read_date(page, "date"),
                "stock": _read_title(page, "stock"),
                "action": _read_select(page, "action"),
                "price": _read_number(page, "price"),
                "reason": _read_rich_text(page, "reason"),
                "emotion": _read_select(page, "emotion"),
            })
        return rows
    except Exception as exc:
        log.error("get_trades failed: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Watchlist
# ──────────────────────────────────────────────────────────────────────────────

def add_watchlist(stock: str, target_price: float, condition: str = "above") -> bool:
    """Add a price alert to the Watchlist."""
    nc = _get_client()
    try:
        nc.pages.create(
            parent={"database_id": config.NOTION_WATCHLIST_DB_ID},
            properties={
                "stock": _title(stock.upper()),
                "target_price": _number(target_price),
                "condition": _select(condition.lower()),
                "status": _select("active"),
            },
        )
        log.info("Added watchlist alert: %s %s %.4f", stock, condition, target_price)
        return True
    except Exception as exc:
        log.error("add_watchlist failed: %s", exc)
        return False


def get_active_watchlist() -> list[dict]:
    """Return all active watchlist entries."""
    nc = _get_client()
    try:
        res = nc.databases.query(
            database_id=config.NOTION_WATCHLIST_DB_ID,
            filter={"property": "status", "select": {"equals": "active"}},
        )
        rows = []
        for page in res.get("results", []):
            rows.append({
                "id": page["id"],
                "stock": _read_title(page, "stock"),
                "target_price": _read_number(page, "target_price"),
                "condition": _read_select(page, "condition"),
                "status": _read_select(page, "status"),
            })
        return rows
    except Exception as exc:
        log.error("get_active_watchlist failed: %s", exc)
        return []


def update_watchlist_status(page_id: str, status: str) -> bool:
    nc = _get_client()
    try:
        nc.pages.update(page_id=page_id, properties={"status": _select(status)})
        return True
    except Exception as exc:
        log.error("update_watchlist_status failed: %s", exc)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Decision Log
# ──────────────────────────────────────────────────────────────────────────────

def log_decision(decision: str, rationale: str, outcome: str = "", reflection: str = "") -> bool:
    """Append an AI decision record."""
    nc = _get_client()
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        nc.pages.create(
            parent={"database_id": config.NOTION_DECISION_LOG_DB_ID},
            properties={
                "date": _date(today),
                "decision": _title(decision),
                "rationale": _rich_text(rationale),
                "outcome": _rich_text(outcome),
                "reflection": _rich_text(reflection),
            },
        )
        log.info("Logged decision: %s", decision)
        return True
    except Exception as exc:
        log.error("log_decision failed: %s", exc)
        return False
