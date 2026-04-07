#!/usr/bin/env python3
"""
update_portfolio.py — portfolio.yaml を取引後に自動更新するスクリプト

使い方:
  # 買い（新規 or 追加）
  python3 update_portfolio.py buy 7974.T 100 8600 --type 現物

  # 売り（一部 or 全部）
  python3 update_portfolio.py sell 1515.T 500 2603

  # 信用新規
  python3 update_portfolio.py buy 285A.T 100 21850 --type 信用 --expiry 2026-12-01

  # 現在のポジション確認
  python3 update_portfolio.py show
"""

import sys
import os
import argparse
from datetime import datetime, date
from copy import deepcopy

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio.yaml")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__))
    from score_engine import read_latest_score, record_trade_entry, record_trade_exit
    _SCORE_ENGINE_AVAILABLE = True
except ImportError:
    _SCORE_ENGINE_AVAILABLE = False

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml が必要です。pip install pyyaml で導入してください。")
    sys.exit(1)


def load():
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save(portfolio):
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        yaml.dump(portfolio, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def find_holding(holdings, ticker, position_type):
    """同一ticker・同一ポジション種別の保有を探す。"""
    for h in holdings:
        if h["ticker"] == ticker and h.get("position_type") == position_type:
            return h
    return None


def cmd_show(portfolio):
    """現在の保有一覧を表示する。"""
    holdings = portfolio.get("holdings", [])
    account = portfolio.get("account", {})
    print(f"総資産: ¥{account.get('total_assets', 0):,}  現金: ¥{account.get('available_cash', 0):,}")
    print()
    credit = [h for h in holdings if h.get("position_type") == "信用"]
    spot   = [h for h in holdings if h.get("position_type") == "現物"]

    if credit:
        print("【信用】")
        for h in credit:
            expiry = h.get("expiry_date", "-")
            print(f"  {h['ticker']} {h.get('name','')} ×{h['quantity']:,}株  "
                  f"取得¥{h['cost_price']:,}  期限:{expiry}")
    if spot:
        print("【現物】")
        for h in spot:
            print(f"  {h['ticker']} {h.get('name','')} ×{h['quantity']:,}株  "
                  f"取得¥{h['cost_price']:,}")

    # trade_log サマリ
    import csv as _csv
    log_path = os.path.join(DATA_DIR, "trade_log.csv")
    if os.path.isfile(log_path):
        with open(log_path, newline="", encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        closed = [r for r in rows if r.get("exit_date")]
        if closed:
            wins = sum(1 for r in closed if float(r.get("pnl_pct") or 0) > 0)
            print(f"\n取引実績: {len(closed)}件クローズ  勝率:{wins/len(closed)*100:.0f}%")


def cmd_buy(portfolio, ticker, qty, price, position_type, expiry, name):
    """買い注文を portfolio.yaml に反映する。"""
    holdings = portfolio.setdefault("holdings", [])
    existing = find_holding(holdings, ticker, position_type)

    if existing:
        # 追加購入 → 平均取得単価を更新
        old_qty   = existing["quantity"]
        old_cost  = existing["cost_price"]
        new_qty   = old_qty + qty
        new_cost  = (old_cost * old_qty + price * qty) / new_qty
        existing["quantity"]   = new_qty
        existing["cost_price"] = round(new_cost, 2)
        print(f"[更新] {ticker} ({position_type}) "
              f"×{old_qty:,} → ×{new_qty:,}株  "
              f"平均取得: ¥{old_cost:,} → ¥{new_cost:,.2f}")
    else:
        # 新規ポジション
        entry = {
            "ticker":        ticker,
            "name":          name or ticker,
            "quantity":      qty,
            "cost_price":    price,
            "position_type": position_type,
        }
        if position_type == "信用":
            entry["open_date"]   = date.today().isoformat()
            entry["expiry_date"] = expiry or ""
            entry["credit_type"] = "制度信用"
        holdings.append(entry)
        print(f"[追加] {ticker} ({position_type}) ×{qty:,}株  取得¥{price:,}")

    save(portfolio)
    if _SCORE_ENGINE_AVAILABLE:
        score_data = read_latest_score(ticker, position_type, DATA_DIR) or {}
        entry_score = {
            "adjusted_score": score_data.get("adjusted_score", ""),
            "signals_fired":  score_data.get("signals_fired", ""),
        }
        record_trade_entry(
            date=date.today().isoformat(), ticker=ticker, action="BUY",
            qty=qty, price=price, position_type=position_type,
            cost_price=price, score_data=entry_score, data_dir=DATA_DIR,
        )
    print(f"✅ portfolio.yaml を更新しました: {PORTFOLIO_PATH}")


def cmd_sell(portfolio, ticker, qty, price, position_type):
    """売り注文を portfolio.yaml に反映する。"""
    holdings = portfolio.get("holdings", [])
    existing = find_holding(holdings, ticker, position_type)

    if not existing:
        print(f"[ERROR] {ticker} ({position_type}) のポジションが見つかりません。")
        cmd_show(portfolio)
        sys.exit(1)

    old_qty = existing["quantity"]
    if qty > old_qty:
        print(f"[ERROR] 売り数量 {qty:,}株 が保有数量 {old_qty:,}株 を超えています。")
        sys.exit(1)

    realized_pnl = (price - existing["cost_price"]) * qty
    pnl_sign = "+" if realized_pnl >= 0 else ""

    if qty == old_qty:
        # 全売り → 保有リストから削除
        holdings.remove(existing)
        print(f"[削除] {ticker} ({position_type}) 全{old_qty:,}株 売却  "
              f"実現損益: {pnl_sign}¥{realized_pnl:,.0f}")
    else:
        # 一部売り → 数量を減らす（取得単価はそのまま）
        existing["quantity"] = old_qty - qty
        print(f"[更新] {ticker} ({position_type}) "
              f"×{old_qty:,} → ×{old_qty - qty:,}株  "
              f"実現損益: {pnl_sign}¥{realized_pnl:,.0f}")

    save(portfolio)
    if _SCORE_ENGINE_AVAILABLE:
        record_trade_exit(
            ticker=ticker, position_type=position_type,
            exit_date=date.today().isoformat(),
            exit_price=price, exit_qty=qty, data_dir=DATA_DIR,
        )
    print(f"✅ portfolio.yaml を更新しました: {PORTFOLIO_PATH}")
    print(f"💡 現金残高も手動で更新してください: available_cash += ¥{price * qty:,}")


def main():
    parser = argparse.ArgumentParser(description="portfolio.yaml 更新ツール")
    sub = parser.add_subparsers(dest="command")

    # show
    sub.add_parser("show", help="現在の保有を表示")

    # buy
    p_buy = sub.add_parser("buy", help="買い注文を記録")
    p_buy.add_argument("ticker",   help="ティッカー (例: 7974.T)")
    p_buy.add_argument("qty",      type=int,   help="株数")
    p_buy.add_argument("price",    type=float, help="取得単価")
    p_buy.add_argument("--type",   dest="position_type", default="現物",
                       choices=["現物", "信用"], help="ポジション種別")
    p_buy.add_argument("--expiry", default="", help="信用期限 (YYYY-MM-DD)")
    p_buy.add_argument("--name",   default="",  help="銘柄名")

    # sell
    p_sell = sub.add_parser("sell", help="売り注文を記録")
    p_sell.add_argument("ticker",  help="ティッカー (例: 1515.T)")
    p_sell.add_argument("qty",     type=int,   help="売却株数")
    p_sell.add_argument("price",   type=float, help="売却単価")
    p_sell.add_argument("--type",  dest="position_type", default="現物",
                        choices=["現物", "信用"], help="ポジション種別")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    portfolio = load()

    if args.command == "show":
        cmd_show(portfolio)
    elif args.command == "buy":
        cmd_buy(portfolio, args.ticker, args.qty, args.price,
                args.position_type, args.expiry, args.name)
    elif args.command == "sell":
        cmd_sell(portfolio, args.ticker, args.qty, args.price,
                 args.position_type)


if __name__ == "__main__":
    main()
