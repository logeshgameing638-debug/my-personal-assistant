"""Tiny local portfolio tracker. Holdings stay on this laptop in portfolio.json.

Analysis only: no trading, no broker login, no orders. Prices come from a
public quote page and can fail or be delayed; always check your broker app
before acting.
"""
import csv
import io
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

PORTFOLIO_PATH = Path(__file__).with_name("portfolio.json")
TRANSACTIONS_PATH = Path(__file__).with_name("transactions.json")
QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
BROWSER_UA = "PersonalAssistant/1.1 (+local app)"


class PortfolioError(Exception):
    """A safe message about portfolio problems."""


def _finite_positive(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PortfolioError(label + " must be a number.") from None
    if not math.isfinite(number) or number <= 0:
        raise PortfolioError(label + " must be a normal number above zero.")
    return number


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
        if symbol and math.isfinite(qty) and math.isfinite(buy) and qty > 0 and buy > 0:
            clean.append({"symbol": symbol, "qty": qty, "buy_price": buy})
    return clean


def save_portfolio(rows):
    PORTFOLIO_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def load_transactions():
    if not TRANSACTIONS_PATH.exists():
        return []
    try:
        rows = json.loads(TRANSACTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _record(kind, symbol, qty, buy_price):
    rows = load_transactions()
    rows.append({"ts": datetime.now().isoformat(timespec="seconds"),
                 "kind": kind, "symbol": symbol,
                 "qty": qty, "buy_price": buy_price})
    try:
        TRANSACTIONS_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    except OSError:
        pass  # history is nice to have; never block the save itself


def _backup_once():
    """Keep a one-time copy of the pre-upgrade holdings next to the original file."""
    backup = PORTFOLIO_PATH.with_name("portfolio.backup.json")
    if PORTFOLIO_PATH.exists() and not backup.exists():
        try:
            backup.write_text(PORTFOLIO_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass


def add_holding(symbol, qty, buy_price):
    """Add to the portfolio. An existing symbol is MERGED: quantities add up and
    the buy price becomes the weighted average. Nothing is silently overwritten."""
    _backup_once()
    symbol = (symbol or "").strip().upper()
    if not symbol or len(symbol) > 30 or not all(c.isalnum() or c in ".-&^" for c in symbol):
        raise PortfolioError("That symbol looks wrong. Example: RELIANCE.NS for NSE stocks.")
    qty = _finite_positive(qty, "Quantity")
    buy_price = _finite_positive(buy_price, "Buy price")
    rows = load_portfolio()
    for row in rows:
        if row["symbol"] == symbol:
            total_qty = row["qty"] + qty
            row["buy_price"] = (row["qty"] * row["buy_price"] + qty * buy_price) / total_qty
            row["qty"] = total_qty
            save_portfolio(rows)
            _record("buy", symbol, qty, buy_price)
            return rows
    rows.append({"symbol": symbol, "qty": qty, "buy_price": buy_price})
    save_portfolio(rows)
    _record("buy", symbol, qty, buy_price)
    return rows


def remove_holding(symbol):
    _backup_once()
    symbol = (symbol or "").strip().upper()
    rows = load_portfolio()
    kept = [r for r in rows if r["symbol"] != symbol]
    removed = [r for r in rows if r["symbol"] == symbol]
    save_portfolio(kept)
    for row in removed:
        _record("remove", symbol, row["qty"], row["buy_price"])
    return kept


def fetch_price(symbol):
    """Best-effort latest price from a public quote endpoint. None when unavailable."""
    url = QUOTE_URL + urllib.parse.quote(symbol) + "?interval=1d&range=5d"
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            result = json.load(response)
        meta = result["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        price = float(price)
        if not math.isfinite(price) or price <= 0:
            return None  # a broken quote is unavailable data, not a crash to zero
        return price
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def pnl_table(rows, price_fn=None):
    """Return (lines, totals). Price None means unavailable. Totals cover ONLY the
    holdings with a live price, so a missing quote never looks like a loss."""
    quote = price_fn or fetch_price
    lines = []
    invested = current = 0.0
    missing = []
    for row in rows:
        price = quote(row["symbol"])
        cost = row["qty"] * row["buy_price"]
        if price is None:
            missing.append(row["symbol"])
            lines.append({"symbol": row["symbol"], "qty": row["qty"],
                          "buy_price": row["buy_price"], "price": None,
                          "value": None, "pnl": None, "pnl_pct": None,
                          "invested": cost})
            continue
        invested += cost
        value = row["qty"] * price
        current += value
        pnl = value - cost
        lines.append({"symbol": row["symbol"], "qty": row["qty"],
                      "buy_price": row["buy_price"], "price": price,
                      "value": value, "pnl": pnl,
                      "pnl_pct": (pnl / cost) * 100 if cost else None,
                      "invested": cost})
    totals = {"invested": invested, "current": current, "pnl": current - invested,
              "pnl_pct": ((current - invested) / invested * 100) if invested else None,
              "missing": missing}
    return lines, totals


def portfolio_summary_text(rows, price_fn=None):
    """Plain-text summary the user can send to the AI for analysis."""
    if not rows:
        return "My portfolio is empty."
    lines, totals = pnl_table(rows, price_fn)
    parts = ["My stock holdings (analysis only, no trades):"]
    for line in lines:
        if line["price"] is None:
            parts.append("- %s: %s shares bought at %.2f each (live price unavailable, excluded from totals)" % (
                line["symbol"], line["qty"], line["buy_price"]))
        else:
            parts.append("- %s: %s shares bought at %.2f, now %.2f, P&L %+.2f (%+.1f%%)" % (
                line["symbol"], line["qty"], line["buy_price"], line["price"],
                line["pnl"], line["pnl_pct"]))
    parts.append("Totals for the %d holding(s) with a live price: invested %.2f, current value %.2f, overall P&L %+.2f." % (
        len(lines) - len(totals["missing"]), totals["invested"], totals["current"], totals["pnl"]))
    if totals["missing"]:
        parts.append("No live price for: " + ", ".join(totals["missing"]) + ". Those are excluded from the totals above.")
    return "\n".join(parts)


def holdings_csv(rows):
    """CSV of current holdings for download."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["symbol", "qty", "buy_price", "invested"])
    for row in rows:
        writer.writerow([row["symbol"], row["qty"], row["buy_price"],
                         round(row["qty"] * row["buy_price"], 2)])
    return out.getvalue()


def transactions_csv():
    """CSV of the local transaction history for download."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["ts", "kind", "symbol", "qty", "buy_price"])
    for row in load_transactions():
        writer.writerow([row.get("ts", ""), row.get("kind", ""), row.get("symbol", ""),
                         row.get("qty", ""), row.get("buy_price", "")])
    return out.getvalue()


def allocation(lines):
    """{symbol: current value} for holdings with a live price, for the chart."""
    return {line["symbol"]: round(line["value"], 2)
            for line in lines if line.get("value") is not None}
