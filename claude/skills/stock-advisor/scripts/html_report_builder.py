#!/usr/bin/env python3
"""Build a readable standalone HTML report from stock-advisor report_context.json."""

import argparse
import html as _html
import json
from pathlib import Path


def esc(value) -> str:
    return _html.escape("" if value is None else str(value), quote=True)


def yen(value) -> str:
    if value is None or value == "":
        return "-"
    return f"¥{float(value):,.0f}"


def pct(value) -> str:
    if value is None or value == "":
        return "-"
    return f"{float(value):+.2f}%"


def number(value, digits: int = 2) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return esc(value)


def action_ja(action: str) -> str:
    return {
        "BUY": "追加買い", "HOLD": "保有継続",
        "REDUCE": "一部売却", "SELL": "全株売却",
        "NO_TRADE": "注文なし",
    }.get(action, action or "HOLD")


def action_display_text(action: str, recommendation: str) -> str:
    if action == "NO_TRADE" and recommendation == "HOLD_BUY":
        return "買い見送り"
    if action == "NO_TRADE" and recommendation == "HOLD_SELL":
        return "売り見送り"
    return action_ja(action)


def risk_posture_ja(value: str) -> str:
    return {
        "neutral": "通常", "protect_profit": "利益保護",
        "rebalance_on_strength": "上昇時リバランス",
        "hold_core": "中核保有", "reduce_risk": "リスク削減",
        "watch": "監視",
    }.get(value or "neutral", value or "通常")


def wf_ja(value: str) -> str:
    return {
        "robust": "頑健", "stable": "安定", "unstable": "不安定",
        "limited": "限定的", "data_insufficient": "価格履歴不足",
        "insufficient_data": "データ不足", "no_trades": "取引なし", "unknown": "不明",
    }.get(value or "", value or "-")


def decision_reason_text(decision: dict) -> str:
    vetoes = decision.get("vetoes", [])
    explanations = decision.get("explanations", [])
    if vetoes and explanations:
        return f"{', '.join(vetoes)}: {'; '.join(explanations)}"
    if vetoes:
        return ", ".join(vetoes)
    if explanations:
        return "; ".join(explanations)
    return ""


def action_class(action: str) -> str:
    return (action or "HOLD").lower()


def badge_class(action: str) -> str:
    return {"BUY": "good", "HOLD": "warn", "REDUCE": "bad", "SELL": "bad", "NO_TRADE": "info"}.get(action or "HOLD", "info")


def pnl_pct_value(holding: dict) -> float:
    cost = float(holding.get("cost_price") or 0)
    price = float(holding.get("current_price") or 0)
    return ((price - cost) / cost * 100) if cost > 0 else 0.0


CSS = """
:root{
  --bg:#07080d;--s1:#0d1117;--s2:#111820;--s3:#151e2a;
  --b1:rgba(255,255,255,.07);--b2:rgba(255,255,255,.14);
  --accent:#e8ff47;--red:#ff4d6d;--blue:#00c6ff;--green:#39ff9b;--orange:#ffb047;
  --text:#dde3ee;--m1:#4a5568;--m2:#8a96a8;
  --font:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',sans-serif;
  --mono:'SFMono-Regular','Menlo','Consolas',monospace;
}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font)}
body:before{content:'';position:fixed;inset:0;background:linear-gradient(rgba(232,255,71,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(232,255,71,.025) 1px,transparent 1px);background-size:48px 48px;pointer-events:none}
.wrap{position:relative;max-width:1180px;margin:0 auto;padding:28px 18px 56px}
.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-bottom:16px}
h1{font-size:24px;line-height:1.2;margin:0;color:var(--accent);font-weight:800}
.meta{font-family:var(--mono);font-size:11px;color:var(--m2);margin-top:6px}
.hero,.panel,.card{background:var(--s1);border:1px solid var(--b1);border-radius:12px}
.hero{padding:18px 20px;margin-bottom:14px}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px}
.metric{background:var(--s2);border:1px solid var(--b1);border-radius:9px;padding:12px}
.metric .label{font-size:10px;color:var(--m2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px}
.metric .value{font-family:var(--mono);font-size:18px;font-weight:700;overflow-wrap:anywhere;min-width:0}
.section{margin-top:14px}
.section-title{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--m2);margin:0 0 8px}
.orders{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.empty{padding:16px;color:var(--m2);font-size:13px}
.gate{width:100%;overflow-x:auto}
.gate table{width:100%;border-collapse:collapse;font-size:12px}
.gate th,.gate td{padding:9px 10px;border-bottom:1px solid var(--b1);text-align:left}
.gate th{color:var(--m2);font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
.gate td{font-family:var(--mono)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px}
.card{padding:14px;position:relative;overflow:hidden}
.card:before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--m1)}
.card.buy:before{background:var(--green)}.card.sell:before,.card.reduce:before{background:var(--red)}
.card.no_trade:before{background:var(--blue)}.card.hold:before{background:var(--orange)}
.card-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:10px}
.ticker{font-family:var(--mono);font-size:16px;font-weight:800;color:var(--accent)}
.name{font-size:12px;color:var(--m2);margin-top:2px}
.badge{display:inline-flex;align-items:center;border-radius:999px;padding:4px 9px;font-family:var(--mono);font-size:11px;border:1px solid var(--b2)}
.badge.good{color:var(--green);background:rgba(57,255,155,.10);border-color:rgba(57,255,155,.28)}
.badge.bad{color:var(--red);background:rgba(255,77,109,.10);border-color:rgba(255,77,109,.28)}
.badge.warn{color:var(--orange);background:rgba(255,176,71,.10);border-color:rgba(255,176,71,.28)}
.badge.info{color:var(--blue);background:rgba(0,198,255,.10);border-color:rgba(0,198,255,.28)}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:10px}
.kv div{background:var(--s3);border:1px solid var(--b1);border-radius:8px;padding:8px}
.kv span{display:block;color:var(--m2);font-size:10px;margin-bottom:4px}
.kv strong{font-family:var(--mono);font-size:13px}
.reason{margin-top:10px;font-size:12px;line-height:1.65;color:var(--text);background:rgba(232,255,71,.06);border:1px solid rgba(232,255,71,.16);border-radius:8px;padding:9px}
.up{color:var(--green)}.down{color:var(--red)}.muted{color:var(--m2)}.mono{font-family:var(--mono)}
@media(max-width:640px){.top{display:block}.grid{grid-template-columns:1fr}.kv{grid-template-columns:1fr}.gate table{font-size:11px}}
"""


def render_metric(label: str, value: str) -> str:
    return f'<div class="metric"><div class="label">{esc(label)}</div><div class="value">{esc(value)}</div></div>'


def render_holding_card(holding: dict, signals: dict, backtest: dict, decisions: dict) -> str:
    ticker = holding.get("ticker", "")
    name = holding.get("name", "")
    position_type = holding.get("position_type", "")
    quantity = holding.get("quantity", 0)
    cost_price = float(holding.get("cost_price") or 0)
    current_price = float(holding.get("current_price") or 0)
    pnl = pnl_pct_value(holding)

    dec = decisions.get(ticker, {})
    action = dec.get("report_action", "HOLD")
    sig = signals.get(ticker, {})
    bt = backtest.get(ticker, {})
    indicators = sig.get("indicators", {})
    score = sig.get("score", {})
    wf = bt.get("walk_forward", {})
    baseline = bt.get("baseline", {})
    consensus = wf.get("consensus", {})

    recommendation = score.get("recommendation", "-")
    price_source = holding.get("price_source", "-")
    price_as_of = holding.get("price_as_of", "-")

    atr_val = float(indicators.get("atr", 0) or 0)
    atr_pct = atr_val / current_price * 100 if current_price > 0 and atr_val > 0 else None
    atr_display = f"{yen(atr_val)} / {atr_pct:.2f}%" if atr_pct is not None else "-"
    display_action = action_display_text(action, recommendation)

    kv_pairs = [
        ("株数", f"{quantity}株"),
        ("取得単価", yen(cost_price)),
        ("現在値", yen(current_price)),
        ("含み損益", f'<span class="{"up" if pnl>0 else "down"}">{pct(pnl)}</span>'),
        ("リスク姿勢", risk_posture_ja(dec.get("risk_posture"))),
        ("シグナル", f'{score.get("score", "-")} / {recommendation}'),
        ("RSI", number(indicators.get("rsi"), 1)),
        ("ATR（日次値幅）", atr_display),
        ("Sharpe", number(baseline.get("sharpe_ratio"), 2)),
        ("WF判定", wf_ja(wf.get("verdict", ""))),
    ]
    # WF diagnostics
    oos_trades = consensus.get("total_test_trades")
    valid_win = consensus.get("valid_test_windows")
    overfit_c = consensus.get("overfit_count")
    dq = consensus.get("data_quality", "")
    if oos_trades is not None:
        kv_pairs.append(("OOS取引", f"{oos_trades}件"))
    if valid_win is not None:
        kv_pairs.append(("有効窓", f"{valid_win}窓"))
    if overfit_c is not None:
        kv_pairs.append(("過学習窓", f"{overfit_c}窓"))
    if dq:
        kv_pairs.append(("WF品質", dq))

    kv_pairs += [
        ("価格ソース", price_source),
        ("価格時刻", price_as_of),
    ]
    kv_html = "\n".join(f"<div><span>{esc(k)}</span><strong>{v}</strong></div>" for k, v in kv_pairs if v)

    reason = decision_reason_text(dec)
    reason_html = f'<div class="reason"><strong>判断理由</strong>: {esc(reason)}</div>' if reason else ""

    risk_flags = dec.get("risk_flags", [])
    flags_html = ""
    if risk_flags:
        flags_html = '<div style="margin-top:6px;font-size:11px;color:var(--m2)"><strong>注意点</strong>: ' + ", ".join(esc(f) for f in risk_flags) + "</div>"

    return f'''<div class="card {action_class(action)}">
<div class="card-head">
<div><div class="ticker">{esc(ticker)}</div><div class="name">{esc(name)} ({esc(position_type)})</div></div>
<div class="badge {badge_class(action)}">{esc(display_action)}</div>
</div>
<div class="kv">{kv_html}</div>
{reason_html}{flags_html}
</div>'''


STRATEGY_LABELS = {
    "default": "標準", "trend": "トレンド", "contrarian": "逆張り",
    "balanced_frequency": "頻度調整", "hold_baseline": "買い持ち基準",
}

GATE_REASON_LABELS = {
    "positive_edge_unvalidated": "優位性あり・OOS検証不足",
    "no_strategy_passed_tradeability_gate": "採用条件未達",
    "strategy_edge_too_small_after_trial_penalty": "試行数補正後の優位性不足",
    "strategy_underperforms_benchmark": "B&Hに劣後",
    "too_few_strategy_trades": "戦略取引数不足",
    "candidate_negative_expected_value": "コスト控除後期待値マイナス",
}


def render_strategy_gate(context: dict) -> str:
    backtest = context.get("backtest", {})
    strategy_review = context.get("strategy_review", {})
    candidates = strategy_review.get("candidates", {})
    seen = set()
    rows = []
    for h in context.get("holdings", []):
        t = h.get("ticker", "")
        if t in seen:
            continue
        seen.add(t)
        bt = backtest.get(t, {})
        cand = candidates.get(t)
        if cand:
            sname = cand.get("strategy", "?")
            sres = bt.get("strategy_comparison", {}).get(sname, {})
            comp = sres.get("benchmark_comparison", {})
            strategy = sname
            status = "candidate"
            tradeable = "reduced" if strategy_review.get("automation_allowed", 0) else "blocked"
            reason = cand.get("reason", comp.get("reason", "positive_edge_unvalidated"))
        else:
            sel = bt.get("strategy_selection", {})
            comp = bt.get("benchmark_comparison", {})
            strategy = sel.get("selected_strategy", "unknown")
            status = strategy
            tradeable = "yes" if sel.get("tradeable") else "no"
            reason = sel.get("reason") or comp.get("reason", "")
        strategy_ja = STRATEGY_LABELS.get(strategy, strategy)
        reason_ja = GATE_REASON_LABELS.get(reason, reason)
        rows.append(f"<tr><td>{esc(t)}</td><td>{esc(strategy_ja)}</td><td>{esc(status)}</td>"
                    f"<td>{esc(str(tradeable))}</td>"
                    f"<td>{esc(pct(comp.get('strategy_total_return')))}</td>"
                    f"<td>{esc(pct(comp.get('benchmark_total_return')))}</td>"
                    f"<td>{esc(pct(comp.get('excess_total_return')))}</td>"
                    f"<td>{esc(reason_ja)}</td></tr>")
    if not rows:
        return ""
    header = "<tr><th>銘柄</th><th>戦略</th><th>状態</th><th>採用可否</th><th>戦略リターン</th><th>B&Hリターン</th><th>超過</th><th>理由</th></tr>"
    return f'<div class="gate"><table>{header}{"".join(rows)}</table></div>'


def render_orders(holdings: list, decisions: dict) -> str:
    active = []
    seen = set()
    for h in holdings:
        t = h.get("ticker", "")
        if t in seen:
            continue
        seen.add(t)
        d = decisions.get(t, {})
        a = d.get("report_action", "HOLD")
        shares = d.get("order_shares", 0)
        if a in ("BUY", "SELL", "REDUCE") and shares > 0:
            active.append(f'<div class="card {action_class(a)}">'
                          f'<div class="ticker">{esc(t)}</div>'
                          f'<div class="name">{esc(h.get("name",""))}</div>'
                          f'<div class="badge {badge_class(a)}">{esc(action_ja(a))} {shares}株</div>'
                          f'</div>')
    if not active:
        return '<div class="empty">No active orders today.</div>'
    return f'<div class="orders">{"".join(active)}</div>'


def render_watchlist(watchlist: list, signals: dict) -> str:
    if not watchlist:
        return ""
    rows = []
    for w in watchlist:
        t = w.get("ticker", "")
        s = signals.get(t, {})
        rec = s.get("score", {}).get("recommendation", "")
        rows.append(f"<tr><td>{esc(t)}</td><td>{esc(w.get('name',''))}</td><td>{esc(rec)}</td></tr>")
    return (f'<section class="section"><h2 class="section-title">Watchlist</h2>'
            f'<div class="gate"><table><tr><th>Ticker</th><th>Name</th><th>Signal</th></tr>{"".join(rows)}</table></div></section>')


def build_html(context: dict) -> str:
    account = context.get("account", {})
    holdings = context.get("holdings", [])
    signals = context.get("signals", {})
    backtest = context.get("backtest", {})
    decisions = context.get("quant_decisions", {}).get("decisions", {})
    strategy_review = context.get("strategy_review", {})
    freshness = context.get("price_freshness", {})
    reference_date = context.get("reference_date", "")

    # WF quality summary
    freq = context.get("frequency_diagnostics", {})
    freq_summary = freq.get("summary", {})
    wf_quality_text = f"thin OOS {freq_summary.get('thin_oos_trades', 0)}/{len(holdings)}, stable {freq_summary.get('sufficient', 0)}/{len(holdings)}"
    if freq_summary.get("sparse"):
        wf_quality_text += f", sparse {freq_summary['sparse']}"

    metrics = "".join([
        render_metric("Total Assets", yen(account.get("total_assets"))),
        render_metric("Cash", yen(account.get("available_cash"))),
        render_metric(account.get("margin_ratio_label", "委託保証金率"), account.get("margin_ratio_text", account.get("margin_ratio", "-"))),
        render_metric("Price Freshness", f"stale_count={freshness.get('stale_count', 0)}"),
        render_metric("Risk Mode", strategy_review.get("risk_mode", "-")),
        render_metric("WF Quality", wf_quality_text),
    ])
    cards = "".join(render_holding_card(h, signals, backtest, decisions) for h in holdings)
    gate = render_strategy_gate(context)
    orders = render_orders(holdings, decisions)
    watchlist = render_watchlist(context.get("watchlist", []), signals)

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock Advisor Daily {esc(reference_date)}</title>
<style>{CSS}</style>
</head>
<body><main class="wrap">
<div class="top"><div><h1>Stock Advisor Daily</h1><div class="meta">reference date: {esc(reference_date)}</div></div></div>
<section class="hero"><div class="metrics">{metrics}</div></section>
<section class="section"><h2 class="section-title">本日のアクション</h2>{orders}</section>
<section class="section"><h2 class="section-title">戦略ゲート</h2>{gate}</section>
<section class="section"><h2 class="section-title">保有銘柄</h2><div class="grid">{cards}</div></section>
{watchlist}
<p class="meta">教育・参考目的のみ。投資判断はご自身の責任で行ってください。</p>
</main></body></html>'''


def update_manifest(output_path: Path) -> None:
    manifest_path = output_path.parent / "run_manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.setdefault("artifacts", {})
    artifacts["html_report"] = str(output_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Build HTML report from stock-advisor report_context.json")
    parser.add_argument("--context", required=True, help="Path to report_context.json")
    parser.add_argument("-o", "--output", required=True, help="Output HTML file path")
    args = parser.parse_args()
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    html_text = build_html(context)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    update_manifest(output)
    print(f"HTML report written to {output}")


if __name__ == "__main__":
    main()
