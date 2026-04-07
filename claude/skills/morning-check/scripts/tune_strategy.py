#!/usr/bin/env python3
"""
tune_strategy.py — シグナル実績分析・ウェイト自動推薦

使い方:
  python3 scripts/tune_strategy.py                  # 分析して推薦を表示
  python3 scripts/tune_strategy.py --apply          # strategy.yaml を自動更新
  python3 scripts/tune_strategy.py --min-trades 5   # 最低サンプル数を変更（デフォルト10）
"""
import sys
import os
import csv
import argparse
from collections import defaultdict

SKILL_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR      = os.path.join(SKILL_DIR, "data")
STRATEGY_PATH = os.path.join(SKILL_DIR, "strategy.yaml")
TRADE_LOG     = os.path.join(DATA_DIR, "trade_log.csv")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score_engine import load_strategy

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


def analyze_signals(trade_log_path: str, min_trades: int = 10) -> dict:
    """
    trade_log.csv を読み込み、シグナル別の実績統計を返す。
    Returns: {signal_name: {"trades": int, "win_rate": float, "avg_pnl": float}}
    """
    if not os.path.isfile(trade_log_path):
        return {}

    with open(trade_log_path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("exit_date")]  # クローズ済みのみ

    if not rows:
        return {}

    signal_data = defaultdict(list)
    for r in rows:
        pnl = r.get("pnl_pct", "")
        if not pnl:
            continue
        pnl_val = float(pnl)
        for sig in r.get("signals_at_entry", "").split(","):
            sig = sig.strip()
            if sig:
                signal_data[sig].append(pnl_val)

    stats = {}
    for sig, pnls in signal_data.items():
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        stats[sig] = {
            "trades":   len(pnls),
            "win_rate": wins / len(pnls),
            "avg_pnl":  round(sum(pnls) / len(pnls), 2),
        }
    return stats


def recommend_adjustments(stats: dict, min_trades: int = 10) -> list:
    """
    シグナル統計から strategy.yaml への調整推薦を生成する。
    Returns: [{"signal": str, "direction": "up"|"down", "reason": str}]
    """
    recs = []
    for sig, s in stats.items():
        if s["trades"] < min_trades:
            continue
        if s["win_rate"] >= 0.65:
            recs.append({"signal": sig, "direction": "up",
                          "reason": f"勝率{s['win_rate']*100:.0f}% ({s['trades']}件)"})
        elif s["win_rate"] <= 0.45:
            recs.append({"signal": sig, "direction": "down",
                          "reason": f"勝率{s['win_rate']*100:.0f}% ({s['trades']}件)"})
    return recs


def apply_adjustments(recs: list, strategy_path: str):
    """推薦を strategy.yaml に反映する（既存スコアを±15%調整）。"""
    if not _YAML_OK:
        print("ERROR: pyyaml が必要です。pip install pyyaml")
        return

    strategy = load_strategy(strategy_path)
    signals  = strategy.get("signals", {})
    changed  = []

    for rec in recs:
        sig = rec["signal"]
        if sig not in signals:
            continue
        old_score = signals[sig]["score"]
        if rec["direction"] == "up":
            new_score = round(old_score * 1.15)
        else:
            new_score = round(old_score * 0.85)
        if new_score != old_score:
            signals[sig]["score"] = new_score
            changed.append(f"  {sig}: {old_score} → {new_score}  ({rec['reason']})")

    if not changed:
        print("変更なし")
        return

    with open(strategy_path, "w", encoding="utf-8") as f:
        yaml.dump(strategy, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print("strategy.yaml を更新しました:")
    for c in changed:
        print(c)


def main():
    parser = argparse.ArgumentParser(description="シグナル実績分析・ウェイト推薦")
    parser.add_argument("--apply",      action="store_true", help="strategy.yaml を自動更新")
    parser.add_argument("--min-trades", type=int, default=10, help="最低トレード数 (default: 10)")
    args = parser.parse_args()

    print(f"trade_log: {TRADE_LOG}")
    stats = analyze_signals(TRADE_LOG, min_trades=args.min_trades)

    if not stats:
        print("クローズ済みトレードがありません。取引実績を蓄積してから再実行してください。")
        return

    print(f"\nシグナル別実績分析 (min_trades={args.min_trades})\n{'─'*55}")
    print(f"{'シグナル':<22} {'勝率':>6} {'平均PnL':>8} {'件数':>5}")
    print(f"{'─'*22} {'─'*6} {'─'*8} {'─'*5}")
    for sig, s in sorted(stats.items(), key=lambda x: -x[1]["win_rate"]):
        flag = " ↑推薦" if s["win_rate"] >= 0.65 else (" ↓推薦" if s["win_rate"] <= 0.45 else "")
        skip = "  (サンプル不足)" if s["trades"] < args.min_trades else ""
        print(f"{sig:<22} {s['win_rate']*100:>5.0f}% {s['avg_pnl']:>+7.1f}% {s['trades']:>5}{flag}{skip}")

    recs = recommend_adjustments(stats, min_trades=args.min_trades)

    if not recs:
        print("\n推薦なし（閾値を下げるには --min-trades を小さくしてください）")
        return

    print(f"\n推薦 strategy.yaml 更新案:")
    for r in recs:
        arrow = "↑ウェイト増" if r["direction"] == "up" else "↓ウェイト減"
        print(f"  {r['signal']:<22} {arrow}  {r['reason']}")

    if args.apply:
        apply_adjustments(recs, STRATEGY_PATH)
    else:
        print("\n※ 適用するには --apply オプションを付けて再実行してください")


if __name__ == "__main__":
    main()
