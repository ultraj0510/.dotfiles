#!/usr/bin/env python3
"""Build a Markdown report skeleton from report_context.json for stock-advisor.

Usage:
    python report_skeleton_builder.py --context report_context.json -o report.md
"""

import argparse
import json
import os
import sys


def yen(value) -> str:
    if value is None:
        return "-"
    return f"¥{float(value):,.0f}"


def action_ja(action: str) -> str:
    return {"BUY": "追加買い", "HOLD": "保有継続",
            "REDUCE": "一部売却", "SELL": "全株売却",
            "NO_TRADE": "取引なし"}.get(action, action)


def risk_posture_ja(value: str) -> str:
    return {"neutral": "通常", "protect_profit": "利益保護", "rebalance_on_strength": "上昇時リバランス", "hold_core": "中核保有", "reduce_risk": "リスク削減", "watch": "監視"}.get(value, value)


def risk_flag_text(flags: list[str]) -> str:
    return ", ".join(flags) if flags else "-"


def advisory_mode_ja(mode: str) -> str:
    return {
        "trail_stop": "トレーリングストップ",
        "trim_on_rebound_rebuy_on_pullback": "反発売り・押し目買い監視",
    }.get(mode, mode)


def format_verdict(verdict: str) -> str:
    mapping = {"robust": "頑健", "stable": "安定",
               "unstable": "不安定", "limited": "限定的",
               "data_insufficient": "価格履歴不足",
               "insufficient_data": "データ不足",
               "no_trades": "取引なし", "unknown": "不明"}
    return mapping.get(verdict, verdict)


def render_strategy_gate_section(items: list[dict]) -> str:
    """Render strategy-vs-benchmark comparison table."""
    lines = [
        "## Strategy Gate",
        "",
        "| Ticker | Selected | Tradeable | Strategy Return | B&H Return | Excess Return | Reason |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]

    for item in items:
        selection = item.get("strategy_selection", {})
        comparison = item.get("benchmark_comparison", {})
        ticker = item.get("ticker", "-")
        selected = selection.get("selected_strategy", "unknown")
        tradeable = "yes" if selection.get("tradeable") else "no"
        strategy_return = comparison.get("strategy_total_return", 0.0)
        benchmark_return = comparison.get("benchmark_total_return", 0.0)
        excess_return = comparison.get("excess_total_return", 0.0)
        reason = comparison.get("reason", selection.get("reason", "unknown"))

        lines.append(
            f"| {ticker} | {selected} | {tradeable} | {strategy_return:.2f}% | "
            f"{benchmark_return:.2f}% | {excess_return:.2f}% | {reason} |"
        )

    lines.append("")
    return "\n".join(lines)


def build_report(context: dict) -> str:
    account = context.get("account", {})
    holdings = context.get("holdings", [])
    watchlist = context.get("watchlist", [])
    signals = context.get("signals", {})
    backtest = context.get("backtest", {})
    correlations = context.get("correlations", {})
    quant_decisions = context.get("quant_decisions", {}).get("decisions", {})
    reference_date = context.get("reference_date", "")

    lines = []
    lines.append(f"# ストックアドバイザー レポート")
    if reference_date:
        lines.append(f"\n> 参考日: {reference_date}")
    lines.append("")

    # Section 1
    lines.append("## 株式分析")
    lines.append("")
    lines.append(f"| 項目 | 値 |")
    lines.append("|---|---|")
    lines.append(f"| 総資産 | {yen(account.get('total_assets'))} |")
    lines.append(f"| 現金残高 | {yen(account.get('available_cash'))} |")
    lines.append(f"| {account.get('margin_ratio_label', '委託保証金率')} | {account.get('margin_ratio_text', account.get('margin_ratio', '-'))} |")

    if correlations:
        avg_corr = correlations.get("avg_correlation")
        risk_conc = correlations.get("risk_concentration", "")
        max_corr = correlations.get("max_correlation", {})
        if avg_corr is not None:
            lines.append(f"| 平均相関係数 | {avg_corr} (リスク集中: {risk_conc}) |")
        if max_corr:
            pair = max_corr.get("pair", [])
            val = max_corr.get("value", "")
            lines.append(f"| 最大相関 | {'/'.join(pair)} ({val}) |")

    lines.append("")

    # Section 2
    lines.append("## 取引指示一覧")
    lines.append("")
    active_orders = []
    seen_order_tickers = set()
    for h in holdings:
        ticker = h["ticker"]
        if ticker in seen_order_tickers:
            continue
        dec = quant_decisions.get(ticker, {})
        action = dec.get("report_action", "HOLD")
        order_shares = dec.get("order_shares", 0)
        if action in ("REDUCE", "SELL", "BUY") and order_shares > 0:
            seen_order_tickers.add(ticker)
            active_orders.append({
                "ticker": ticker,
                "name": h["name"],
                "action": action,
                "order_shares": order_shares,
                "order_type": dec.get("order_type", ""),
                "limit_price": dec.get("limit_price"),
                "confidence": dec.get("confidence", ""),
                "vetoes": dec.get("vetoes", []),
                "risk_flags": dec.get("risk_flags", []),
                "explanations": dec.get("explanations", []),
            })

    if active_orders:
        lines.append("| 銘柄コード | 名称 | 指示 | 株数 | 注文方法 | 指値 | 注意点 |")
        lines.append("|---|---|---|---|---|---|---|")
        for o in active_orders:
            limit_str = yen(o["limit_price"]) if o["limit_price"] else "-"
            status_flags = o["vetoes"] or o["risk_flags"]
            status_str = risk_flag_text(status_flags) if status_flags else "-"
            lines.append(f"| {o['ticker']} | {o['name']} | {action_ja(o['action'])} | {o['order_shares']} | {o['order_type']} | {limit_str} | {status_str} |")
    else:
        lines.append("現在注文のある指示はありません。")

    lines.append("")

    # Strategy Gate section
    strategy_items = []
    seen_gate_tickers = set()
    for h in holdings:
        ticker = h["ticker"]
        if ticker in seen_gate_tickers:
            continue
        seen_gate_tickers.add(ticker)
        dec = quant_decisions.get(ticker, {})
        # Strategy gate data is in the backtest section of the context
        bt = backtest.get(ticker, {})
        item = {
            "ticker": ticker,
            "strategy_selection": bt.get("strategy_selection", {}),
            "benchmark_comparison": bt.get("benchmark_comparison", {}),
        }
        if item["strategy_selection"] or item["benchmark_comparison"]:
            strategy_items.append(item)

    if strategy_items:
        lines.append(render_strategy_gate_section(strategy_items))
        lines.append("")

    # Section 3
    lines.append("## 銘柄別詳細")
    lines.append("")

    for h in holdings:
        ticker = h["ticker"]
        name = h["name"]
        position_type = h.get("position_type", "")
        quantity = h.get("quantity", 0)
        cost_price = h.get("cost_price", 0)
        current_price = h.get("current_price", 0)
        expiry_date = h.get("expiry_date")
        dec = quant_decisions.get(ticker, {})
        action = dec.get("report_action", "HOLD")
        pnl_pct = ((float(current_price) - float(cost_price)) / float(cost_price) * 100) if cost_price and float(cost_price) > 0 else 0
        sig_info = signals.get(ticker, {})
        bt = backtest.get(ticker, {})

        pnl_str = f"（{pnl_pct:+.2f}%）"
        lines.append(f"### {ticker} {name}（{position_type}） — {action_ja(action)}{pnl_str}")
        lines.append("")

        lines.append("| 項目 | 値 |")
        lines.append("|---|---|")
        lines.append(f"| 保有株数 | {quantity} |")
        lines.append(f"| 平均購入価格 | {yen(cost_price)} |")
        lines.append(f"| 現価 | {yen(current_price)} |")
        lines.append(f"| 含み損益率 | {pnl_pct:+.2f}% |")
        if expiry_date:
            lines.append(f"| 信用期限 | {expiry_date} |")
        posture = dec.get("risk_posture") or "neutral"
        lines.append(f"| リスク姿勢 | {risk_posture_ja(posture)} |")
        lines.append(f"| ストップ目安価格 | {yen(dec.get('protective_stop_price'))} |")

        risk_flags_list = dec.get("risk_flags", [])
        if risk_flags_list:
            lines.append(f"| 注意点 | {risk_flag_text(risk_flags_list)} |")

        plan = dec.get("advisory_plan") or {}
        if plan:
            lines.append(f"| 戦略 | {advisory_mode_ja(plan.get('mode', ''))} |")
            if plan.get("trim_trigger_price") is not None:
                lines.append(f"| 反発売り目安 | {yen(plan['trim_trigger_price'])} |")
            if plan.get("reentry_watch_price") is not None:
                lines.append(f"| 押し目買い監視 | {yen(plan['reentry_watch_price'])} |")

        # Signal section
        score_obj = sig_info.get("score", {})
        score_val = score_obj.get("score", "")
        rec = score_obj.get("recommendation", "")
        ind = sig_info.get("indicators", {})
        rows = 0
        if score_val != "" or rec:
            lines.append(f"| スコア | {score_val}{' (' + rec + ')' if rec else ''} |")
            rows += 1
        if ind.get("rsi") is not None:
            lines.append(f"| RSI | {ind['rsi']} |")
            rows += 1
        if ind.get("atr") is not None:
            lines.append(f"| ATR | {ind['atr']} |")
            rows += 1

        # Backtest summary
        bt_baseline = bt.get("baseline", {})
        bt_wf = bt.get("walk_forward", {})
        if bt_baseline.get("trade_count", 0) > 0:
            lines.append(f"| バックテスト取引回数 | {bt_baseline.get('trade_count', 0)} |")
            lines.append(f"| 勝率 | {bt_baseline.get('win_rate', '-')}% |")
            lines.append(f"| 平均勝ち | {bt_baseline.get('avg_win_pct', '-')}% |")
            lines.append(f"| 平均負け | {bt_baseline.get('avg_loss_pct', '-')}% |")
            lines.append(f"| Sharpe | {bt_baseline.get('sharpe_ratio', '-')} |")
            kurt = bt_baseline.get("kurtosis")
            if kurt is not None:
                lines.append(f"| 尖度 (kurtosis) | {kurt} |")
            if bt_wf:
                wf_verdict = bt_wf.get("verdict", "")
                consensus = bt_wf.get("consensus", {})
                if wf_verdict:
                    lines.append(f"| WF判定 | {format_verdict(wf_verdict)} |")
                if consensus.get("data_quality"):
                    lines.append(f"| WFデータ品質 | {consensus['data_quality']} |")
                if consensus.get("total_test_trades") is not None:
                    lines.append(f"| WFテスト取引数 | {consensus['total_test_trades']} |")
                if bt_wf.get("overfit_detected"):
                    lines.append(f"| 過学習 | 検出 |")

        lines.append("")

    # Watchlist section under 銘柄別詳細
    if watchlist:
        lines.append("### ウォッチリスト")
        lines.append("")
        for w in watchlist:
            ticker = w["ticker"]
            name = w["name"]
            sig_info = signals.get(ticker, {})
            rec = sig_info.get("score", {}).get("recommendation", "")
            lines.append(f"- {ticker} {name}（{rec}）")
        lines.append("")

    # Section 4
    lines.append("## 本日の優先アクション")
    lines.append("")

    if active_orders:
        for o in active_orders:
            veto_str = f"（ヴェトー: {', '.join(o['vetoes'])}）" if o["vetoes"] else ""
            lines.append(f"- **{o['ticker']} {o['name']}**: {action_ja(o['action'])} {o['order_shares']}株"
                         f" {veto_str}")
    else:
        lines.append("現在実行中のアクションはありません。")

    if watchlist:
        for w in watchlist:
            lines.append(f"- {w['ticker']} {w['name']}: ウォッチリスト継続")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build Markdown report skeleton from report_context.json")
    parser.add_argument("--context", required=True, help="Path to report_context.json")
    parser.add_argument("-o", "--output", required=True, help="Output Markdown file path")
    args = parser.parse_args()

    with open(args.context, encoding="utf-8") as f:
        context = json.load(f)

    report = build_report(context)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
