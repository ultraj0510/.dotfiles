#!/usr/bin/env python3
"""
fetch_portfolio.py — ポートフォリオデータ取得・計算スクリプト（LLM不使用）

使い方:
  python3 fetch_portfolio.py          # 要アクション銘柄のみ表示（デフォルト）
  python3 fetch_portfolio.py --all    # 全銘柄表示

Python の検索順序:
  1. MORNING_CHECK_PYTHON 環境変数
  2. /Users/fujie/code/TradingAgents/.venv/bin/python3
  3. /Users/fujie/code/playground/stock-price-analyze/venv/bin/python3
  4. システムの python3
"""

import sys
import os
import subprocess

# ── venv 自動検出 ────────────────────────────────────────────────
# このスクリプト自身が正しい Python で実行されているか確認し、
# 必要なら適切な Python に再実行（re-exec）する。
def _find_python():
    env_override = os.environ.get("MORNING_CHECK_PYTHON")
    if env_override and os.path.isfile(env_override):
        return env_override
    candidates = [
        "/Users/fujie/code/TradingAgents/.venv/bin/python3",
        "/Users/fujie/code/playground/stock-price-analyze/.venv/bin/python3",
        "/Users/fujie/code/playground/stock-price-analyze/venv/bin/python3",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return sys.executable

def _ensure_deps():
    """必要なライブラリが揃っていなければ再実行する。"""
    try:
        import yfinance, pandas, yaml  # noqa
    except ImportError:
        python = _find_python()
        if python != sys.executable:
            os.execv(python, [python] + sys.argv)
        print("ERROR: yfinance / pandas / pyyaml が必要です。")
        print("  pip install yfinance pandas pyyaml")
        sys.exit(1)

_ensure_deps()

# ── 本体インポート ────────────────────────────────────────────────
import argparse
import warnings
from datetime import datetime, date, timedelta

warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import yaml

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio.yaml")
STRATEGY_PATH = os.path.join(os.path.dirname(__file__), "..", "strategy.yaml")
DATA_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")

try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__))
    from score_engine import load_strategy, score_holding, append_daily_scores
    _SCORE_ENGINE_AVAILABLE = True
except ImportError:
    _SCORE_ENGINE_AVAILABLE = False

TODAY = datetime.today().strftime("%Y-%m-%d")

MACRO_SYMBOLS = {
    "^GSPC":    ("S&P 500",        "米国株"),
    "^IXIC":    ("NASDAQ",         "米国株"),
    "^N225":    ("日経225",         "日本株"),
    "NKD=F":    ("日経先物(CME)",   "日本株先物"),
    "USDJPY=X": ("USD/JPY",        "為替"),
    "DX-Y.NYB": ("DXY ドル指数",   "為替"),
    "^VIX":     ("VIX 恐怖指数",   "リスク"),
    "^TNX":     ("米10年債利回り",  "金利"),
}


# ── ユーティリティ ────────────────────────────────────────────────

def next_trading_day(from_date: date | None = None) -> date:
    """土日を除いた次の取引日（簡易版: 日本祝日は未考慮）。"""
    d = from_date or date.today()
    # 今日が月〜金かつ今まだ前場前なら今日を返す
    now_hour = datetime.now().hour
    if d.weekday() < 5 and now_hour < 9:
        return d
    # それ以外は翌営業日
    d += timedelta(days=1)
    while d.weekday() >= 5:  # 5=土, 6=日
        d += timedelta(days=1)
    return d


def days_until(date_str: str) -> int:
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (target - date.today()).days


def fmt_pct(v):
    return "N/A" if v is None else f"{v:+.1f}%"


def fmt_price(v):
    return "N/A" if v is None else f"¥{v:,.0f}"


def load_portfolio():
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── データ取得 ────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period_days: int = 300) -> pd.DataFrame:
    try:
        df = yf.Ticker(ticker).history(period=f"{period_days}d")
        if df.empty:
            return pd.DataFrame()
        df.index = df.index.tz_localize(None)
        return df[df.index <= pd.Timestamp(TODAY)]
    except Exception as e:
        print(f"  [警告] {ticker} データ取得失敗: {e}", file=sys.stderr)
        return pd.DataFrame()


def compute_metrics(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 5:
        return {}
    close  = df["Close"]
    volume = df["Volume"]
    cur    = close.iloc[-1]

    ret_5d  = (cur / close.iloc[-6]  - 1) * 100 if len(close) >= 6  else None
    ret_20d = (cur / close.iloc[-21] - 1) * 100 if len(close) >= 21 else None

    window  = min(252, len(close))
    hi_52w  = close.iloc[-window:].max()
    lo_52w  = close.iloc[-window:].min()
    pos_52w = (cur - lo_52w) / (hi_52w - lo_52w) * 100 if hi_52w != lo_52w else None

    rsi = None
    if len(close) >= 15:
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = (100 - 100 / (1 + rs)).iloc[-1]

    bb_mid   = close.rolling(20).mean().iloc[-1]  if len(close) >= 20 else None
    bb_std   = close.rolling(20).std().iloc[-1]   if len(close) >= 20 else None
    bb_upper = bb_mid + 2 * bb_std if bb_mid and bb_std else None
    bb_lower = bb_mid - 2 * bb_std if bb_mid and bb_std else None

    avg_vol   = volume.rolling(20).mean().iloc[-1] if len(volume) >= 20 else None
    vol_ratio = volume.iloc[-1] / avg_vol if avg_vol else None

    avg_vol_s  = volume.rolling(20, min_periods=1).mean()
    vol_ratio_s = volume / avg_vol_s.replace(0, float("nan"))
    daily_ret  = close.pct_change() * 100
    notable = []
    for i in range(max(1, len(df) - 10), len(df)):
        r = daily_ret.iloc[i]
        if abs(r) >= 5.0:
            vr  = vol_ratio_s.iloc[i]
            vrs = f"{vr:.1f}x" if not pd.isna(vr) else "?"
            notable.append(f"{df.index[i].strftime('%Y-%m-%d')} {r:+.1f}% "
                           f"{'急騰' if r > 0 else '急落'} (出来高{vrs})")

    return dict(current=cur, ret_5d=ret_5d, ret_20d=ret_20d,
                pos_52w=pos_52w, high_52w=hi_52w, low_52w=lo_52w,
                rsi=rsi, bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
                vol_ratio=vol_ratio, notable=notable)


# ── アナリスト・空売り残高 ────────────────────────────────────────

def fetch_analyst_short_data(ticker: str) -> dict:
    """
    アナリスト目標株価と機構空売り残高を yfinance から取得する。
    日本株はカバレッジが薄い場合があるため、取得できた項目だけ返す。
    """
    result = {}
    try:
        t    = yf.Ticker(ticker)
        info = t.info  # 1回だけ取得してキャッシュ

        # ── アナリスト目標株価 ──────────────────────────────────
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low  = info.get("targetLowPrice")
        n_analysts  = info.get("numberOfAnalystOpinions")
        rec_key     = info.get("recommendationKey", "")   # "buy","hold","sell" etc.
        rec_mean    = info.get("recommendationMean")      # 1=Strong Buy … 5=Strong Sell

        # yfinance の新 API (analyst_price_targets) をフォールバックとして試行
        if target_mean is None:
            try:
                apt = t.analyst_price_targets
                if apt and isinstance(apt, dict):
                    target_mean = apt.get("mean")
                    target_high = apt.get("high")
                    target_low  = apt.get("low")
            except Exception:
                pass

        if target_mean is not None:
            result["target_mean"] = target_mean
        if target_high is not None:
            result["target_high"] = target_high
        if target_low is not None:
            result["target_low"]  = target_low
        if n_analysts is not None:
            result["n_analysts"]  = n_analysts
        if rec_key:
            result["rec_key"]     = rec_key
        if rec_mean is not None:
            result["rec_mean"]    = rec_mean

        # ── 機構空売り残高 ──────────────────────────────────────
        short_pct   = info.get("shortPercentOfFloat")   # Float に占める空売り比率
        short_ratio = info.get("shortRatio")             # 返済日数（日数が多い＝ショートスクイーズ余地）
        shares_short       = info.get("sharesShort")
        shares_short_prior = info.get("sharesShortPriorMonth")

        if short_pct is not None:
            result["short_pct"]   = short_pct * 100  # 0.05 → 5.0%
        if short_ratio is not None:
            result["short_ratio"] = short_ratio
        if shares_short is not None and shares_short_prior is not None:
            change_pct = (shares_short / shares_short_prior - 1) * 100
            result["short_change_pct"] = change_pct   # 前月比変化率

    except Exception as e:
        result["error"] = str(e)

    return result


# ── 要アクション判定 ──────────────────────────────────────────────

def needs_action(holding: dict, metrics: dict, analyst: dict | None = None) -> tuple[bool, list[str]]:
    """
    この銘柄が今日アクションを要するか判定し、
    (True/False, 理由リスト) を返す。
    信用ポジションは常に True。
    """
    reasons = []
    if holding.get("position_type") == "信用":
        return True, ["信用ポジション（常に表示）"]

    m = metrics
    if not m:
        return False, []

    pnl_pct = (m["current"] / holding["cost_price"] - 1) * 100 if m.get("current") else None

    if pnl_pct is not None and pnl_pct <= -15:
        reasons.append(f"含み損 {pnl_pct:+.1f}%")
    if pnl_pct is not None and pnl_pct >= 30:
        reasons.append(f"含み益 {pnl_pct:+.1f}% (利確検討)")
    if m.get("rsi") and m["rsi"] <= 35:
        reasons.append(f"RSI {m['rsi']:.1f} 売られすぎ")
    if m.get("rsi") and m["rsi"] >= 68:
        reasons.append(f"RSI {m['rsi']:.1f} 買われすぎ")
    if m.get("pos_52w") is not None and m["pos_52w"] <= 15:
        reasons.append(f"52週位置 {m['pos_52w']:.0f}% (底値圏)")
    if m.get("pos_52w") is not None and m["pos_52w"] >= 85:
        reasons.append(f"52週位置 {m['pos_52w']:.0f}% (高値圏)")
    if m.get("notable"):
        reasons.append(f"直近急変動: {m['notable'][-1]}")

    # アナリスト目標との乖離
    if analyst and m.get("current"):
        cur = m["current"]
        if "target_mean" in analyst:
            upside = (analyst["target_mean"] / cur - 1) * 100
            if upside >= 25:
                reasons.append(f"アナリスト目標比+{upside:.0f}% 割安")
            elif upside <= -15:
                reasons.append(f"アナリスト目標比{upside:.0f}% 割高")
        # 空売り残高急増
        if analyst.get("short_change_pct") is not None and analyst["short_change_pct"] >= 20:
            reasons.append(f"空売り前月比+{analyst['short_change_pct']:.0f}% 増加")

    return len(reasons) > 0, reasons


# ── マクロ表示 ────────────────────────────────────────────────────

def fetch_macro_context():
    results = {}
    for symbol, (name, cat) in MACRO_SYMBOLS.items():
        try:
            df = yf.Ticker(symbol).history(period="10d")
            if df.empty or len(df) < 2:
                results[symbol] = {"name": name, "category": cat, "error": "データなし"}
                continue
            df.index = df.index.tz_localize(None) if df.index.tz else df.index
            latest = df["Close"].iloc[-1]
            prev   = df["Close"].iloc[-2]
            c1     = (latest / prev - 1) * 100
            c5     = (latest / df["Close"].iloc[-6] - 1) * 100 if len(df) >= 6 else None
            results[symbol] = dict(name=name, category=cat,
                                   latest=latest, change_1d=c1, change_5d=c5,
                                   last_date=df.index[-1].strftime("%Y-%m-%d"))
        except Exception as e:
            results[symbol] = {"name": name, "category": cat, "error": str(e)}
    return results


def print_macro_context(macro):
    print("【マクロ市場環境】")
    print("-" * 55)
    for cat in ["米国株", "日本株先物", "日本株", "為替", "金利", "リスク"]:
        items = [(s, d) for s, d in macro.items() if d.get("category") == cat]
        if not items:
            continue
        print(f"  [{cat}]")
        for symbol, d in items:
            if "error" in d:
                print(f"  {d['name']}: 取得失敗"); continue
            v, c1, c5 = d["latest"], d["change_1d"], d.get("change_5d")
            arr = "▲" if c1 >= 0 else "▼"
            c5s = f"  5d:{c5:+.1f}%" if c5 is not None else ""
            if symbol == "USDJPY=X":
                print(f"  {d['name']}: {v:.2f}円  {arr}{abs(c1):.2f}%{c5s}")
            elif symbol == "DX-Y.NYB":
                print(f"  {d['name']}: {v:.2f}  {arr}{abs(c1):.2f}%{c5s}")
            elif symbol == "^TNX":
                print(f"  {d['name']}: {v:.3f}%  {arr}{abs(c1):.2f}%{c5s}")
            elif symbol == "^VIX":
                flag = (" 🚨 極度の恐怖" if v >= 30 else
                        " ⚠️ 警戒域"    if v >= 20 else
                        " 🟢 過信域"    if v <= 13 else "")
                print(f"  {d['name']}: {v:.1f}{flag}  {arr}{abs(c1):.2f}%{c5s}")
            elif symbol == "NKD=F":
                n225 = macro.get("^N225", {})
                gap_s = ""
                if "latest" in n225:
                    gp = (v - n225["latest"]) / n225["latest"] * 100
                    gap_s = f"  現物比:{gp:+.1f}%({v - n225['latest']:+.0f}円)"
                print(f"  {d['name']}: {v:,.0f}円  {arr}{abs(c1):.2f}%{gap_s}")
            else:
                print(f"  {d['name']}: {v:,.2f}  {arr}{abs(c1):.2f}%{c5s}")

    print()
    print("  [マクロ温度感]")
    sp5  = macro.get("^GSPC", {})
    vix  = macro.get("^VIX",  {})
    usdjpy = macro.get("USDJPY=X", {})
    nkf  = macro.get("NKD=F", {})
    sigs = []
    if "latest" in vix:
        if vix["latest"] >= 25: sigs.append(f"VIX{vix['latest']:.0f}→リスクオフ警戒")
        elif vix["latest"] <= 15: sigs.append(f"VIX{vix['latest']:.0f}→リスクオン")
    if "change_1d" in sp5:
        if sp5["change_1d"] <= -1.5: sigs.append(f"S&P500前日{sp5['change_1d']:+.1f}%→売り圧力")
        elif sp5["change_1d"] >= 1.0: sigs.append(f"S&P500前日{sp5['change_1d']:+.1f}%→追い風")
    if "latest" in usdjpy:
        if usdjpy["latest"] >= 155: sigs.append(f"ドル円{usdjpy['latest']:.1f}円→輸出株追い風")
        elif usdjpy["latest"] <= 140: sigs.append(f"ドル円{usdjpy['latest']:.1f}円→円高・輸出株逆風")
    if "latest" in nkf and "latest" in macro.get("^N225", {}):
        gp = (nkf["latest"] - macro["^N225"]["latest"]) / macro["^N225"]["latest"] * 100
        if gp >= 0.5:  sigs.append(f"先物+{gp:.1f}%→寄付きギャップアップ注意")
        elif gp <= -0.5: sigs.append(f"先物{gp:.1f}%→寄付き窓開け下落注意")
    for s in sigs:
        print(f"  ⚡ {s}")
    if not sigs:
        print("  ✅ 特段の異常なし")
    print()


# ── 夜間PTS・プレマーケット取得 ──────────────────────────────────

def fetch_pts_data(ticker: str) -> dict:
    """
    yfinance から夜間PTS（postMarketPrice）と寄り前気配（preMarketPrice）を取得する。
    取得できた項目だけ返す。日本株はカバレッジが薄い場合がある。
    """
    result = {}
    try:
        info = yf.Ticker(ticker).fast_info
        prev_close = getattr(info, "previous_close", None) or getattr(info, "regular_market_previous_close", None)
        post = getattr(info, "post_market_price", None)
        pre  = getattr(info, "pre_market_price",  None)
        if post and prev_close:
            result["post_price"]  = post
            result["post_change"] = (post / prev_close - 1) * 100
        if pre and prev_close:
            result["pre_price"]   = pre
            result["pre_change"]  = (pre / prev_close - 1) * 100
    except Exception:
        pass
    return result


# ── 銘柄表示 ──────────────────────────────────────────────────────

def print_holding(h, m, show_detail=True, analyst: dict | None = None, pts: dict | None = None):
    ticker = h["ticker"]
    name   = h.get("name", ticker)
    qty    = h["quantity"]
    cost   = h["cost_price"]
    cur    = m.get("current")
    pnl    = (cur - cost) * qty if cur else None
    pnl_pct = (cur / cost - 1) * 100 if cur else None

    print(f"{ticker} {name} ×{qty:,}株  {fmt_price(cur)}  "
          f"損益:{fmt_pct(pnl_pct)} "
          f"({'+' if pnl and pnl>=0 else ''}¥{pnl:,.0f})" if pnl is not None
          else f"{ticker} {name} ×{qty:,}株  {fmt_price(cur)}")

    if h.get("position_type") == "信用" and h.get("expiry_date"):
        rem  = days_until(h["expiry_date"])
        flag = " 🚨 30日以内" if rem <= 30 else " ⚠️ 60日以内" if rem <= 60 else ""
        print(f"  信用期限: {h['expiry_date']} (残{rem}日){flag}")

    if pts:
        if "post_price" in pts:
            arr = "▲" if pts["post_change"] >= 0 else "▼"
            flag = (" 🔴 急落" if pts["post_change"] <= -3 else
                    " 🟢 急騰" if pts["post_change"] >= 3  else "")
            print(f"  夜間PTS: {fmt_price(pts['post_price'])}  {arr}{abs(pts['post_change']):.2f}%{flag}")
        if "pre_price" in pts:
            arr = "▲" if pts["pre_change"] >= 0 else "▼"
            print(f"  寄り前: {fmt_price(pts['pre_price'])}  {arr}{abs(pts['pre_change']):.2f}%")

    if show_detail and m:
        pos_s = f"  52週:{m['pos_52w']:.0f}%" if m.get("pos_52w") is not None else ""
        rsi   = m.get("rsi")
        rsi_f = " ⚠️ 売られすぎ" if rsi and rsi < 30 else (" △ 割高" if rsi and rsi > 70 else "")
        print(f"  5d:{fmt_pct(m.get('ret_5d'))}  20d:{fmt_pct(m.get('ret_20d'))}{pos_s}")
        if rsi:
            print(f"  RSI:{rsi:.1f}{rsi_f}  "
                  f"BB下限:{fmt_price(m.get('bb_lower'))}  BB上限:{fmt_price(m.get('bb_upper'))}")
        for note in m.get("notable", []):
            print(f"  📌 {note}")

    # ── アナリスト情報 ───────────────────────────────────────────
    if show_detail and analyst and "error" not in analyst and cur:
        parts = []
        if "target_mean" in analyst:
            upside = (analyst["target_mean"] / cur - 1) * 100
            upside_flag = (" 🟢 割安" if upside >= 20 else
                           " 🔴 割高" if upside <= -15 else "")
            parts.append(
                f"目標:{fmt_price(analyst['target_mean'])} ({upside:+.0f}%{upside_flag})"
            )
            if "target_low" in analyst and "target_high" in analyst:
                parts.append(
                    f"[{fmt_price(analyst['target_low'])}〜{fmt_price(analyst['target_high'])}]"
                )
        if "n_analysts" in analyst:
            parts.append(f"{analyst['n_analysts']}人")
        if "rec_key" in analyst:
            rec_map = {"strongBuy": "強気買い", "buy": "買い", "hold": "中立",
                       "sell": "売り", "strongSell": "強気売り"}
            parts.append(f"推奨:{rec_map.get(analyst['rec_key'], analyst['rec_key'])}")
        if parts:
            print(f"  📊 アナリスト: {' | '.join(parts)}")

        # 空売り残高
        short_parts = []
        if "short_pct" in analyst:
            sp = analyst["short_pct"]
            sp_flag = " ⚠️ 高水準" if sp >= 10 else ""
            short_parts.append(f"Float比{sp:.1f}%{sp_flag}")
        if "short_ratio" in analyst:
            sr = analyst["short_ratio"]
            sr_flag = " ⚡ スクイーズ余地" if sr >= 5 else ""
            short_parts.append(f"返済{sr:.1f}日{sr_flag}")
        if "short_change_pct" in analyst:
            sc = analyst["short_change_pct"]
            sc_flag = " ↑増加" if sc >= 10 else (" ↓減少" if sc <= -10 else "")
            short_parts.append(f"前月比{sc:+.0f}%{sc_flag}")
        if short_parts:
            print(f"  📉 空売り: {' | '.join(short_parts)}")


# ── メイン ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="モーニングチェック データ取得")
    parser.add_argument("--all", action="store_true",
                        help="全銘柄を詳細表示（デフォルトは要アクション銘柄のみ）")
    args = parser.parse_args()

    portfolio = load_portfolio()
    account   = portfolio.get("account", {})
    holdings  = portfolio.get("holdings", [])

    next_td = next_trading_day()

    print(f"{'='*55}")
    print(f"  MORNING CHECK  {TODAY}  次の取引日: {next_td.strftime('%Y-%m-%d (%a)')}")
    print(f"{'='*55}")
    print(f"総資産: {fmt_price(account.get('total_assets'))}  "
          f"現金: {fmt_price(account.get('available_cash'))}")
    print()

    macro = fetch_macro_context()
    print_macro_context(macro)

    # データ取得（同一ticker は1回だけ）
    tickers = list({h["ticker"] for h in holdings})
    data = {t: {"df": fetch_ohlcv(t), "metrics": {}, "analyst": {}, "pts": {}} for t in tickers}
    for t in tickers:
        data[t]["metrics"] = compute_metrics(data[t]["df"])
        data[t]["analyst"] = fetch_analyst_short_data(t)
        data[t]["pts"]     = fetch_pts_data(t)

    # ── スコアリング ──────────────────────────────────────────────
    scores = {}  # key: (ticker, position_type) -> score_result
    if _SCORE_ENGINE_AVAILABLE:
        strategy = load_strategy(STRATEGY_PATH)
        for h in holdings:
            t = h["ticker"]
            result = score_holding(
                h, data[t]["metrics"], data[t]["analyst"], macro, strategy
            )
            scores[(t, h.get("position_type", "現物"))] = result

    credit_h = [h for h in holdings if h.get("position_type") == "信用"]
    spot_h   = [h for h in holdings if h.get("position_type") == "現物"]

    # 信用ポジション（常に全件詳細表示）
    if credit_h:
        print("【信用ポジション】")
        print("-" * 55)
        for h in credit_h:
            print_holding(h, data[h["ticker"]]["metrics"], show_detail=True,
                          analyst=data[h["ticker"]]["analyst"],
                          pts=data[h["ticker"]]["pts"])
            print()

    # 現物ポジション
    if spot_h:
        action_h  = []
        passive_h = []
        for h in spot_h:
            m = data[h["ticker"]]["metrics"]
            key = (h["ticker"], h.get("position_type", "現物"))
            if _SCORE_ENGINE_AVAILABLE and key in scores:
                sc = scores[key]
                flag = sc["action_flag"]
                reasons = sc["signals_fired"] + [
                    f"score={sc['adjusted_score']:+.0f}(raw={sc['raw_score']:+d}×{sc['macro_multiplier']})"
                ]
            else:
                flag, reasons = needs_action(h, m, analyst=data[h["ticker"]]["analyst"])
            if flag:
                action_h.append((h, m, reasons))
            else:
                passive_h.append((h, m))

        if action_h:
            print("【現物 — 要アクション】")
            print("-" * 55)
            for h, m, reasons in action_h:
                print(f"  ▶ 理由: {' / '.join(reasons)}")
                print_holding(h, m, show_detail=True,
                              analyst=data[h["ticker"]]["analyst"],
                              pts=data[h["ticker"]]["pts"])
                print()

        if passive_h:
            if args.all:
                print("【現物 — 継続監視】")
                print("-" * 55)
                for h, m in passive_h:
                    print_holding(h, m, show_detail=True,
                                  analyst=data[h["ticker"]]["analyst"],
                                  pts=data[h["ticker"]]["pts"])
                    print()
            else:
                print("【現物 — 継続監視（異常なし）】")
                print("-" * 55)
                for h, m in passive_h:
                    cur     = m.get("current")
                    pnl_pct = (cur / h["cost_price"] - 1) * 100 if cur else None
                    print(f"  {h['ticker']} {h.get('name','')} ×{h['quantity']}株  "
                          f"{fmt_price(cur)}  {fmt_pct(pnl_pct)}")
                print(f"  ※ 詳細は --all オプションで表示")
                print()

        total_pnl = sum(
            (data[h["ticker"]]["metrics"].get("current", h["cost_price"]) - h["cost_price"]) * h["quantity"]
            for h in spot_h
        )
        print(f"現物合計含み損益: {'+' if total_pnl >= 0 else ''}¥{total_pnl:,.0f}")
        print()

    # ── daily_scores.csv への保存 ─────────────────────────────────
    if _SCORE_ENGINE_AVAILABLE and scores:
        today_str = datetime.today().strftime("%Y-%m-%d")
        rows = []
        for h in holdings:
            t    = h["ticker"]
            pt   = h.get("position_type", "現物")
            key  = (t, pt)
            sc   = scores.get(key, {})
            m    = data[t]["metrics"]
            rows.append({
                "date":             today_str,
                "ticker":           t,
                "position_type":    pt,
                "raw_score":        sc.get("raw_score", 0),
                "adjusted_score":   sc.get("adjusted_score", 0.0),
                "macro_multiplier": sc.get("macro_multiplier", 1.0),
                "signals_fired":    ",".join(sc.get("signals_fired", [])),
                "current_price":    m.get("current", ""),
                "rsi":              m.get("rsi", ""),
                "bb_pos":           (round((m["current"] - m["bb_lower"]) / m["bb_lower"], 4)
                                     if m.get("current") and m.get("bb_lower") else ""),
                "w52_pos":          m.get("pos_52w", ""),
                "action_flag":      sc.get("action_flag", False),
            })
        append_daily_scores(rows, DATA_DIR)
        print(f"  [スコア保存] {len(rows)} 銘柄のスコアを daily_scores.csv に追記")

    print("=" * 55)
    print("上記データをもとに分析・推奨を提示してください。")
    print("=" * 55)


if __name__ == "__main__":
    main()
