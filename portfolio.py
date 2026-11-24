"""Tiny local portfolio tracker. Holdings stay on this laptop in portfolio.json.

Analysis only: no trading, no broker login, no orders. Prices come from a
public quote page and can fail or be delayed; always check your broker app
before acting.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PORTFOLIO_PATH = Path(__file__).with_name("portfolio.json")
QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
BROWSER_UA = "PersonalAssistant/1.1 (+local app)"


class PortfolioError(Exception):
    """A safe message about portfolio problems."""


def load_portfolio():
    if not PORTFOLIO_PATH.exists():
        return []
    try:
        rows = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PortfolioError("Cannot read portfolio.json. Fix or delete that file in the app folder.")
    clean = []
    for row in rows if isinstance(rows, list) else []:
        try:
            symbol = str(row["symbol"]).strip().upper()
            qty = float(row["qty"])
            buy = float(row["buy_price"])
        except (KeyError, TypeError, ValueError):
            continue
        if symbol and qty > 0 and buy > 0:
            clean.append({"symbol": symbol, "qty": qty, "buy_price": buy})
    return clean


def save_portfolio(rows):
    PORTFOLIO_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def add_holding(symbol, qty, buy_price):
    symbol = (symbol or "").strip().upper()
    if not symbol or len(symbol) > 30 or not all(c.isalnum() or c in ".-&^" for c in symbol):
        raise PortfolioError("That symbol looks wrong. Example: RELIANCE.NS for NSE stocks.")
    try:
        qty = float(qty)
        buy_price = float(buy_price)
    except (TypeError, ValueError):
        raise PortfolioError("Quantity and buy price must be numbers.") from None
    if qty <= 0 or buy_price <= 0:
        raise PortfolioError("Quantity and buy price must be above zero.")
    rows = load_portfolio()
    for row in rows:
        if row["symbol"] == symbol:
            row["qty"] = qty
            row["buy_price"] = buy_price
            save_portfolio(rows)
            return rows
    rows.append({"symbol": symbol, "qty": qty, "buy_price": buy_price})
    save_portfolio(rows)
    return rows


def remove_holding(symbol):
    symbol = (symbol or "").strip().upper()
    rows = [r for r in load_portfolio() if r["symbol"] != symbol]
    save_portfolio(rows)
    return rows


def fetch_price(symbol):
    """Best-effort latest price from a public quote endpoint. None when unavailable."""
    url = QUOTE_URL + urllib.parse.quote(symbol) + "?interval=1d&range=5d"
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            result = json.load(response)
        meta = result["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        return float(price) if price else None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def pnl_table(rows):
    """Return (lines, totals) with per-holding P&L. Price None means unavailable."""
    lines = []
    invested = current = 0.0
    missing = []
    for row in rows:
        price = fetch_price(row["symbol"])
        cost = row["qty"] * row["buy_price"]
        invested += cost
        if price is None:
            missing.append(row["symbol"])
            lines.append({"symbol": row["symbol"], "qty": row["qty"],
                          "buy_price": row["buy_price"], "price": None,
                          "value": None, "pnl": None})
            continue
        value = row["qty"] * price
        current += value
        lines.append({"symbol": row["symbol"], "qty": row["qty"],
                      "buy_price": row["buy_price"], "price": price,
                      "value": value, "pnl": value - cost})
    totals = {"invested": invested, "current": current, "pnl": current - invested,
              "missing": missing}
    return lines, totals


def portfolio_summary_text(rows):
    """Plain-text summary the user can send to the AI for analysis."""
    if not rows:
        return "My portfolio is empty."
    lines, totals = pnl_table(rows)
    parts = ["My stock holdings (analysis only, no trades):"]
    for line in lines:
        if line["price"] is None:
            parts.append("- %s: %s shares bought at %.2f each (live price unavailable)" % (
                line["symbol"], line["qty"], line["buy_price"]))
        else:
            parts.append("- %s: %s shares bought at %.2f, now %.2f, P&L %+.2f" % (
                line["symbol"], line["qty"], line["buy_price"], line["price"], line["pnl"]))
    parts.append("Total invested %.2f, current value %.2f, overall P&L %+.2f." % (
        totals["invested"], totals["current"], totals["pnl"]))
    return "\n".join(parts)
