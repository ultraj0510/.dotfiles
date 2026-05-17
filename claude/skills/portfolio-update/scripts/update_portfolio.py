#!/usr/bin/env python3
"""market-pulse: portfolio.yaml更新スクリプト.

使い方:
  python3 update_portfolio.py show
  python3 update_portfolio.py buy <ticker> <quantity> <price> [--type 現物|信用]
  python3 update_portfolio.py sell <ticker> <quantity> <price> [--type 現物|信用]
"""

import argparse
import os
import sys
import yaml
from datetime import date

STOCK_ANALYZE_DIR = os.path.expanduser("~/code/playground/stock-price-analyze")
PORTFOLIO_PATH = os.path.join(STOCK_ANALYZE_DIR, "portfolio.yaml")


def load() -> dict:
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save(data: dict):
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def cmd_show():
    pf = load()
    holdings = pf.get("holdings", [])
    account = pf.get("account", {})

    print(f"Total Assets: ¥{account.get('total_assets', 0):,}")
    print(f"Available Cash: ¥{account.get('available_cash', 0):,}")
    print()
    print(f"{'Ticker':<10} {'Name':<20} {'Type':<6} {'Qty':>6} {'Cost':>10} {'Pct':>8}")
    print("-" * 70)

    total_value = 0
    for h in holdings:
        ticker = h.get("ticker", "")
        name = h.get("name", "")[:18]
        ptype = h.get("position_type", "")
        qty = h.get("quantity", 0)
        cost = h.get("cost_price", 0)
        value = cost * qty
        total_value += value
        pct = value / account.get("total_assets", 1) * 100 if account.get("total_assets") else 0

        print(f"{ticker:<10} {name:<20} {ptype:<6} {qty:>6} ¥{cost:>9,.0f} {pct:>7.1f}%")

    print("-" * 70)
    print(f"Cost basis total: ¥{total_value:,.0f}")


def cmd_buy(args):
    pf = load()
    holdings = pf.setdefault("holdings", [])

    for h in holdings:
        if h.get("ticker") == args.ticker and h.get("position_type") == args.type:
            total_qty = h["quantity"] + args.quantity
            total_cost = h["cost_price"] * h["quantity"] + args.price * args.quantity
            h["quantity"] = total_qty
            h["cost_price"] = round(total_cost / total_qty, 2)
            save(pf)
            print(f"Updated: {args.ticker} x{h['quantity']} @ ¥{h['cost_price']:,.0f}")
            return

    entry = {
        "ticker": args.ticker,
        "name": args.ticker,
        "quantity": args.quantity,
        "cost_price": args.price,
        "position_type": args.type,
    }
    if args.type == "信用":
        entry["open_date"] = date.today().isoformat()
        entry["expiry_date"] = (date.today().replace(year=date.today().year + 1)).isoformat()
        entry["credit_type"] = "制度信用"

    holdings.append(entry)
    save(pf)
    print(f"Added: {args.ticker} x{args.quantity} @ ¥{args.price:,.0f} ({args.type})")


def cmd_sell(args):
    pf = load()
    holdings = pf.get("holdings", [])

    for h in holdings:
        if h.get("ticker") == args.ticker and h.get("position_type") == args.type:
            if args.quantity > h["quantity"]:
                print(f"[ERROR] 売却数量({args.quantity})が保有数量({h['quantity']})を超えています")
                sys.exit(1)

            h["quantity"] -= args.quantity
            pnl = (args.price - h["cost_price"]) * args.quantity

            if h["quantity"] == 0:
                holdings.remove(h)
                print(f"Removed: {args.ticker} (全売却)")
            else:
                print(f"Updated: {args.ticker} x{h['quantity']} remaining")

            print(f"Realized PnL: ¥{pnl:+,.0f}")
            save(pf)
            return

    print(f"[ERROR] {args.ticker} ({args.type}) の保有が見つかりません")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="portfolio.yaml 更新")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("show", help="現在の保有表示")

    buy_parser = sub.add_parser("buy", help="買い追加")
    buy_parser.add_argument("ticker")
    buy_parser.add_argument("quantity", type=int)
    buy_parser.add_argument("price", type=float)
    buy_parser.add_argument("--type", default="現物", choices=["現物", "信用"])

    sell_parser = sub.add_parser("sell", help="売り/一部売り")
    sell_parser.add_argument("ticker")
    sell_parser.add_argument("quantity", type=int)
    sell_parser.add_argument("price", type=float)
    sell_parser.add_argument("--type", default="現物", choices=["現物", "信用"])

    args = parser.parse_args()

    if not os.path.exists(PORTFOLIO_PATH):
        print(f"[ERROR] portfolio.yaml not found at {PORTFOLIO_PATH}")
        sys.exit(1)

    if args.cmd == "show":
        cmd_show()
    elif args.cmd == "buy":
        cmd_buy(args)
    elif args.cmd == "sell":
        cmd_sell(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
