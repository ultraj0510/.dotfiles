#!/usr/bin/env python3
"""market-pulse: 保有銘柄データ取得スクリプト.

stock-price-analyze の分析モジュールを再利用し、全保有銘柄の
テクニカル指標・シグナル・信用リスク・含み損益を一括取得する。

使い方:
  python3 fetch_portfolio.py          # 要アクション銘柄のみ
  python3 fetch_portfolio.py --all    # 全銘柄詳細表示
  python3 fetch_portfolio.py --skip-sync  # SBI自動同期スキップ
"""

import argparse
import sys
import os
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --- Python discovery ---
def _discover_python() -> str:
    """SKILL.md規定の順序でPythonを検出する。"""
    forced = os.environ.get("MORNING_CHECK_PYTHON")
    if forced:
        return forced

    candidates = [
        os.path.expanduser("~/code/deepcode/TradingAgents/.venv/bin/python3"),
        os.path.expanduser("~/code/playground/stock-price-analyze/.venv/bin/python3"),
        os.path.expanduser("~/code/playground/stock-price-analyze/venv312/bin/python3"),
        os.path.expanduser("~/code/playground/stock-price-analyze/venv/bin/python3"),
    ]
    for python in candidates:
        if os.path.isfile(python) and os.access(python, os.X_OK):
            return python

    return "python3"


PYTHON = _discover_python()

_STOCK_ANALYZE_DIR = os.path.expanduser("~/code/playground/stock-price-analyze")
if os.path.isdir(_STOCK_ANALYZE_DIR) and _STOCK_ANALYZE_DIR not in sys.path:
    sys.path.insert(0, _STOCK_ANALYZE_DIR)

import yaml


def load_portfolio(portfolio_path: str = None) -> dict:
    if portfolio_path is None:
        portfolio_path = os.path.join(_STOCK_ANALYZE_DIR, "portfolio.yaml")
    with open(portfolio_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def fetch_stock_data(ticker: str, fallback_price: float = None) -> dict | None:
    """1銘柄の株価・指標・シグナルを取得する。

    If yfinance fails but fallback_price is provided (e.g. from SBI sync),
    returns a minimal dict with the SBI price. This prevents ¥0/data-failure
    displays when the market is closed.
    """
    price = None
    rsi = bb_lower = bb_upper = ma20 = atr = 0.0
    signals = []
    signal_desc = ""
    market_phase = "neutral"
    surge = False

    try:
        from data.fetcher import get_stock_data
        from indicators.calculator import calculate_indicators, get_latest_values
        from signals.engine import check_signal, describe_signals

        df = get_stock_data(ticker, period="1y")
        if df is not None:
            df = calculate_indicators(df)
            values = get_latest_values(df)
            signals = check_signal(values)
            signal_desc = describe_signals(signals)

            p = values.get("price")
            if p is not None and not (isinstance(p, (int, float)) and p != p):
                price = float(p.iloc[0] if hasattr(p, "iloc") else p)

            rsi = round(float(values.get("rsi", 0) or 0), 1)
            bb_lower = round(float(values.get("bb_lower", 0) or 0), 0)
            bb_upper = round(float(values.get("bb_upper", 0) or 0), 0)
            ma20 = round(float(values.get("ma20", 0) or 0), 0)
            atr = round(float(values.get("atr", 0) or 0), 0)
            market_phase = values.get("market_phase", "neutral")
            surge = bool(values.get("surge_days", 0) > 0)
    except ImportError:
        pass

    # Use SBI-synced fallback price if yfinance failed
    if price is None and fallback_price and fallback_price > 0:
        price = fallback_price

    if price is None or price <= 0:
        return None

    return {
        "price": round(price, 0),
        "rsi": rsi,
        "bb_lower": bb_lower,
        "bb_upper": bb_upper,
        "ma20": ma20,
        "signals": signals,
        "signal_desc": signal_desc,
        "market_phase": market_phase,
        "atr": atr,
        "surge_detected": surge,
    }


def calc_credit_risks(holding: dict, current_price: float, account_margin_ratio: float | None = None) -> dict:
    """信用建玉のリスク情報を計算する。

    account_margin_ratio: SBI口座全体の委託保証金率（%）。追証判定は口座単位で行う。
    """
    try:
        from risk.margin import calculate_margin_risk, calculate_interest_cost, calculate_expiry
    except ImportError:
        return {}

    qty = holding.get("quantity", 0)
    cost = holding.get("cost_price", 0)
    result = {}

    margin = calculate_margin_risk(qty, cost, current_price)
    # 追証判定は口座全体の委託保証金率で判断（SBI: 最低保証金維持率20%）
    if account_margin_ratio is not None:
        margin["account_margin_ratio"] = account_margin_ratio
        margin["margin_call_triggered"] = account_margin_ratio < 20.0
    result["margin_risk"] = margin

    open_str = holding.get("open_date")
    if open_str:
        open_date = date.fromisoformat(open_str)
        interest = calculate_interest_cost(qty, cost, open_date)
        result["interest"] = interest

    expiry_str = holding.get("expiry_date")
    if expiry_str:
        expiry_date = date.fromisoformat(expiry_str)
        result["expiry"] = calculate_expiry(expiry_date)

    return result


def score_action(holding: dict, stock: dict | None, credit_risks: dict) -> int:
    """アクション優先度スコアを計算する（高いほど緊急）。"""
    score = 0
    if stock is None:
        return 99  # データ取得失敗は最優先

    # 信用期限が迫っている（max 40点）
    expiry = credit_risks.get("expiry", {})
    days = expiry.get("days_remaining", 999)
    if days < 30:
        score += 40
    elif days < 60:
        score += 20

    # 含み損が大きい（max 30点）
    cost = holding.get("cost_price", 0)
    qty = holding.get("quantity", 0)
    price = stock.get("price", cost)
    if cost > 0:
        pnl_pct = (price - cost) / cost * 100
        if pnl_pct < -15:
            score += 30
        elif pnl_pct < -8:
            score += 15
        elif pnl_pct < -3:
            score += 5

    # シグナルが強い（max 20点）
    n_signals = len(stock.get("signals", []))
    if n_signals >= 2:
        score += 20
    elif n_signals == 1:
        score += 10

    # 信用維持率が危険（max 10点）
    margin = credit_risks.get("margin_risk", {})
    if margin.get("margin_call_triggered"):
        score += 10
    elif margin.get("alert_triggered"):
        score += 5

    return score


def format_output(holdings: list, portfolios: list, show_all: bool = False):
    """SKILL.md Step 1 が要求する形式で出力する。"""
    account = portfolios.get("account", {})
    total_assets = account.get("total_assets", 0)
    available_cash = account.get("available_cash", 0)
    account_margin_ratio = account.get("margin_ratio")

    margin_str = f"  |  Margin: {account_margin_ratio:.1f}%" if account_margin_ratio else ""
    print(f"## Portfolio Snapshot {date.today().isoformat()}")
    print(f"Total Assets: ¥{total_assets:,}  |  Cash: ¥{available_cash:,}{margin_str}")
    print()

    actionable = []
    for h in holdings:
        ticker = h.get("ticker")
        name = h.get("name", ticker)
        pos_type = h.get("position_type", "現物")
        qty = h.get("quantity", 0)
        cost = h.get("cost_price", 0)

        fallback = h.get("current_price") or cost
        stock = fetch_stock_data(ticker, fallback_price=fallback)
        credit_risks = {}
        if pos_type == "信用":
            if stock:
                credit_risks = calc_credit_risks(h, stock["price"], account_margin_ratio)

        score = score_action(h, stock, credit_risks)
        has_action = score >= 5

        if has_action or show_all:
            actionable.append((score, ticker, name, h, stock, credit_risks, pos_type, qty, cost))

    actionable.sort(key=lambda x: x[0], reverse=True)

    if not actionable:
        print("## 全銘柄 正常（要アクションなし）")
        return

    # マクロ環境取得
    def _yf_close_vals(data):
        """yfinance >=0.5 returns MultiIndex columns; extract Close as 1-D array."""
        import pandas as pd
        if data.empty:
            return None
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.values

    def _last_trading_date(data):
        """Extract the last trading date from yfinance data (works on weekends)."""
        if data.empty:
            return None
        ts = data.index[-1]
        return ts.date() if hasattr(ts, "date") else ts

    today = date.today()
    effective_date = today

    try:
        import yfinance as yf
        vix_data = yf.download("^VIX", period="5d", progress=False)
        vix_close = _yf_close_vals(vix_data)
        vix_val = float(vix_close[-1]) if vix_close is not None and len(vix_close) > 0 else None
        if not vix_data.empty:
            effective_date = _last_trading_date(vix_data)
    except Exception:
        vix_val = None

    try:
        import yfinance as yf
        sp500_data = yf.download("^GSPC", period="5d", progress=False)
        sp500_close = _yf_close_vals(sp500_data)
        if sp500_close is not None and len(sp500_close) >= 2:
            sp500_prev = float(sp500_close[-2])
            sp500_curr = float(sp500_close[-1])
            sp500_chg = round((sp500_curr - sp500_prev) / sp500_prev * 100, 2)
        else:
            sp500_chg = None
        if effective_date == today and not sp500_data.empty:
            effective_date = _last_trading_date(sp500_data)
    except Exception:
        sp500_chg = None

    data_note = ""
    if effective_date < today:
        data_note = f" (data as of {effective_date.isoformat()}, market closed)"
    print(f"## Macro Context{data_note}")
    print(f"VIX: {vix_val:.1f}" if vix_val else "VIX: N/A")
    print(f"S&P500 前日比: {sp500_chg:+.2f}%" if sp500_chg is not None else "S&P500: N/A")
    print()

    print(f"## 要アクション銘柄 ({len(actionable)}件)")
    print()

    for score, ticker, name, h, stock, credit_risks, pos_type, qty, cost in actionable:
        price = stock["price"] if stock else 0
        pnl = (price - cost) * qty if stock and cost else 0
        pnl_pct = round((price - cost) / cost * 100, 1) if stock and cost else 0

        print(f"### {name} ({ticker}) — Score: {score}")
        print(f"  Type: {pos_type}  |  Qty: {qty}株  |  Cost: ¥{cost:,.0f}  |  Price: ¥{price:,.0f}")
        print(f"  PnL: ¥{pnl:+,.0f} ({pnl_pct:+.1f}%)")

        if stock:
            print(f"  RSI: {stock['rsi']}  |  MA20: ¥{stock['ma20']:,.0f}  |  BB: ¥{stock['bb_lower']:,.0f}〜¥{stock['bb_upper']:,.0f}")
            print(f"  Signals: {stock['signal_desc']}  |  Phase: {stock['market_phase']}")
            if stock.get("surge_detected"):
                print(f"  [WARN] 急騰検出中")

        expiry = credit_risks.get("expiry", {})
        if expiry:
            print(f"  Expiry: {expiry.get('expiry_date')} ({expiry.get('days_remaining')}日) [{expiry.get('urgency')}]")

        margin = credit_risks.get("margin_risk", {})
        if margin:
            call_price = margin.get("margin_call_price", 0)
            print(f"  MarginCall Limit: ¥{call_price:,.0f}  |  Position PnL: {margin.get('current_margin_ratio'):.1f}%")
            if margin.get("margin_call_triggered"):
                print(f"  [CRITICAL] 口座委託保証金率 {margin.get('account_margin_ratio', 0):.1f}% < 20% → 追証発生中！")
            elif margin.get("account_margin_ratio"):
                print(f"  Account Margin: {margin['account_margin_ratio']:.1f}% (healthy)")

        interest = credit_risks.get("interest", {})
        if interest:
            print(f"  Interest: ¥{interest.get('total_interest'):,.0f} ({interest.get('holding_days')}日)")

        print()
        sys.stdout.flush()


# --- SBI sync (delegates to portfolio-core) ---

_CORE = os.path.expanduser("~/.dotfiles/portfolio-core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from cookie_store import read_cookie as _read_sbi_cookie
from sbi_fetch import sync_from_sbi as _sync_from_sbi


def main():
    parser = argparse.ArgumentParser(description="market-pulse データ取得")
    parser.add_argument("--all", action="store_true", help="全銘柄詳細表示")
    parser.add_argument("--skip-sync", action="store_true", help="SBI自動同期スキップ")
    parser.add_argument("--use-cache-on-fail", action="store_true", help="SBI同期失敗時にキャッシュ表示を続行")
    args = parser.parse_args()

    portfolio_path = os.path.join(_STOCK_ANALYZE_DIR, "portfolio.yaml")

    # SBI自動同期 (uses portfolio-core)
    cookie = _read_sbi_cookie()
    if not args.skip_sync and cookie:
        status = _sync_from_sbi(portfolio_path, cookie)
        if status != "ok":
            if args.use_cache_on_fail:
                last_upd = "不明"
                if os.path.isfile(portfolio_path):
                    try:
                        cached = load_portfolio(portfolio_path)
                        last_upd = cached.get("last_successful_sync_at") or cached.get("last_updated", "不明")
                    except Exception:
                        pass
                print(f"[NOTICE] SBI同期に失敗したためキャッシュデータを表示します（status: {status}, 最終SBI同期: {last_upd}）")
            elif status == "auth_expired":
                print("[AUTH_EXPIRED] SBIセッションが切れています。", file=sys.stderr)
                sys.exit(2)
            else:
                print(f"[ERROR] SBI同期に失敗しました ({status})。", file=sys.stderr)
                sys.exit(1)
        print()
    elif not args.skip_sync and not cookie:
        print("[WARN] SBI_COOKIEが設定されていません。", file=sys.stderr)

    if not os.path.isfile(portfolio_path):
        print(f"[ERROR] portfolio.yaml not found at {portfolio_path}", file=sys.stderr)
        sys.exit(1)

    portfolio = load_portfolio(portfolio_path)

    # --- Macro context ---
    print(f"## Portfolio Snapshot {date.today().isoformat()}")
    account = portfolio.get("account", {})
    total = account.get("total_assets", 0)
    cash = account.get("available_cash", 0)
    margin_ratio_str = f"{(account.get('margin_ratio', 0)):.1f}%" if account.get("margin_ratio") else "?"
    print(f"Total Assets: ¥{total:,.0f}  |  Cash: ¥{cash:,.0f}  |  Margin: {margin_ratio_str}")

    # Macro data
    try:
        import yfinance as _yf
        vix = _yf.download("^VIX", period="5d", progress=False, auto_adjust=True)
        if not vix.empty:
            _vix_val = float(vix["Close"].iloc[-1])
            print(f"\n## Macro Context (data as of {_last_trading_date()}, market closed)")
            print(f"VIX: {_vix_val:.1f}")
        spx = _yf.download("^GSPC", period="5d", progress=False, auto_adjust=True)
        if not spx.empty and len(spx) >= 2:
            _spx_chg = (float(spx["Close"].iloc[-1]) - float(spx["Close"].iloc[-2])) / float(spx["Close"].iloc[-2]) * 100
            print(f"S&P500 前日比: {_spx_chg:+.2f}%")
    except Exception:
        pass

    holdings = portfolio.get("holdings", [])
    if not holdings:
        print("\n保有銘柄がありません。portfolio.yaml を確認してください。")
        return

    # --- Analysis ---
    results = []
    for h in holdings:
        ticker = h.get("ticker")
        if not ticker:
            continue
        stock = fetch_stock_data(ticker, fallback_price=h.get("current_price"))
        credit_risks = calc_credit_risks(h, account) if h.get("position_type") == "信用" else {}
        score = score_action(h, stock, credit_risks)
        results.append({
            "holding": h,
            "stock": stock,
            "score": score,
            "credit_risks": credit_risks,
        })

    # Sort by score descending
    results.sort(key=lambda r: r["score"], reverse=True)

    if not args.all:
        # Show only actionable items (score >= 5) or all if requested
        actionable = [r for r in results if r["score"] >= 5]
        if actionable:
            print(f"\n## 要アクション銘柄 ({len(actionable)}件)\n")
        else:
            print("\n## 要アクション銘柄 (0件)\n")
            print("全銘柄アクション不要です。")
        display_results = actionable if actionable else results
        format_output(display_results, portfolios=[], show_all=False)
    else:
        print(f"\n## 全銘柄詳細 ({len(results)}件)\n")
        format_output(results, portfolios=[], show_all=True)


if __name__ == "__main__":
    main()
