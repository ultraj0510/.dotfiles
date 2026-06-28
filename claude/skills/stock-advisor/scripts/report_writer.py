# stock-advisor/scripts/report_writer.py
"""Render report.md from daily_actions.json and analysis.json v2.0."""
import json
from pathlib import Path


def build_report(daily_actions_path: Path, data_dir: Path) -> str:
    """Render report.md from daily_actions.json and latest analysis.json files."""
    da = json.loads(Path(daily_actions_path).read_text())
    lines: list[str] = []

    # Header
    lines.append(f"# ポートフォリオ日次レポート — {da['generated_at'][:10]}")
    lines.append("")

    # Account summary
    _render_account(lines, da.get("account", {}))
    _render_actions(lines, da.get("actions", []))
    _render_monitor(lines, da.get("actions", []))
    _render_watchlist(lines, da.get("actions", []))
    _render_errors(lines, da.get("errors", {}))
    lines.append("---")
    lines.append("")

    # Per-ticker details
    for action in da.get("actions", []):
        ticker = action["ticker"]
        # Load analysis.json via latest.json
        latest_path = data_dir / ticker / "latest.json"
        analysis = None
        if latest_path.exists():
            try:
                latest = json.loads(latest_path.read_text())
                run_id = latest.get("latest_run_id")
                if run_id:
                    a_path = data_dir / ticker / "runs" / run_id / "analysis.json"
                    if a_path.exists():
                        analysis = json.loads(a_path.read_text())
            except Exception:
                pass

        _render_ticker_detail(lines, action, analysis)

    return "\n".join(lines)


def _render_account(lines, account):
    lines.append("## 口座サマリー")
    lines.append("")
    lines.append("| 項目 | 値 |")
    lines.append("|------|-----|")
    for key, label in [("total_assets", "総資産"), ("available_cash", "現金余力"),
                        ("margin_ratio", "委託保証金率"), ("buying_power", "買付余力"),
                        ("margin_principal", "信用元本")]:
        val = account.get(key)
        if val is not None:
            if key in ("margin_ratio",):
                lines.append(f"| {label} | {val}% |")
            else:
                lines.append(f"| {label} | {_yen(val)} |")
    lines.append("")


def _render_actions(lines, actions):
    action_needed = [a for a in actions if a["today_action"] != "NO_TRADE"]
    lines.append("## 本日のアクション")
    lines.append("")
    lines.append(f"**要対応: {len(action_needed)}件** / 全{len(actions)}銘柄")
    lines.append("")
    if action_needed:
        lines.append("| 銘柄 | 投資判断 | 行動 | 理由 |")
        lines.append("|------|---------|------|------|")
        for a in action_needed:
            reason = a.get("override_reason") or a["analysis"]["reasoning"][:40]
            lines.append(f"| {a['ticker']} {_esc(a['name'])} | {a['analysis']['investment_rating']} | {a['today_action']} | {reason} |")
    else:
        lines.append("なし")
    lines.append("")


def _render_monitor(lines, actions):
    monitor = [a for a in actions if a["today_action"] == "NO_TRADE"]
    lines.append("## 監視継続")
    lines.append("")
    if monitor:
        lines.append("| 銘柄 | 投資判断 | 執行姿勢 | テクニカル | 備考 |")
        lines.append("|------|---------|---------|-----------|------|")
        for a in monitor:
            ana = a["analysis"]
            lines.append(f"| {a['ticker']} {_esc(a['name'])} | {ana['investment_rating']} | {ana['execution_posture']} | {ana.get('technical_signal_raw','-')} | {ana['reasoning'][:40]} |")
    lines.append("")


def _render_watchlist(lines, actions):
    # Watchlist items are actions with empty holdings
    wl = [a for a in actions if not a.get("holdings")]
    if not wl:
        return
    lines.append("## watchlist")
    lines.append("")
    lines.append("| 銘柄 | 投資判断 | テクニカル | 備考 |")
    lines.append("|------|---------|-----------|------|")
    for a in wl:
        ana = a["analysis"]
        lines.append(f"| {a['ticker']} {_esc(a['name'])} | {ana['investment_rating']} | {ana.get('technical_signal_raw','-')} | {ana['reasoning'][:40]} |")
    lines.append("")


def _render_errors(lines, errors):
    if not errors:
        return
    h_errors = errors.get("holdings", [])
    w_errors = errors.get("watchlist", [])
    if h_errors or w_errors:
        lines.append("## 分析エラー")
        lines.append("")
        for e in h_errors:
            lines.append(f"- **[保有] {e['ticker']}**: {e['error']}")
        for e in w_errors:
            lines.append(f"- [watchlist] {e['ticker']}: {e['error']}")
        lines.append("")


def _render_ticker_detail(lines, action, analysis):
    lines.append(f"### {action['ticker']} {action['name']}")
    lines.append("")

    # Holdings
    if action.get("holdings"):
        lines.append("#### 保有状況")
        lines.append("")
        lines.append("| 口座 | 数量 | 取得単価 | 現値 | 含み損益 | ウェイト |")
        lines.append("|------|------|---------|------|---------|---------|")
        for h in action["holdings"]:
            pnl = f"{h['pnl_pct']:+.2f}%"
            lines.append(f"| {h.get('account','-')} | {h['quantity']} | {_yen(h['cost_price'])} | {_yen(h['current_price'])} | {pnl} | {h['weight_pct']:.2f}% |")
        lines.append("")

    # Judgment
    lines.append("#### 投資判断")
    lines.append("")
    lines.append(f"- **投資判断:** {action['analysis']['investment_rating']}")
    lines.append(f"- **本日の行動:** {action['today_action']}")
    if action.get("overridden"):
        lines.append(f"- **上書き理由:** {action['override_reason']}")
    lines.append(f"- **理由:** {action['analysis']['reasoning']}")
    lines.append("")

    # Forecast
    if analysis and analysis.get("forecast"):
        fc = analysis["forecast"]
        target_label = "当日の4本値目安" if fc.get("target") == "same_day" else "翌営業日の4本値目安"
        lines.append(f"#### {target_label}")
        lines.append("")
        if fc.get("confidence") == "unavailable":
            lines.append(f"4本値目安: データ不足（{fc.get('unavailable_reason', '')}）")
        else:
            lines.append(_format_forecast_row(fc))
        lines.append("")

    # Technical indicators
    if analysis and analysis.get("technical", {}).get("indicators"):
        ind = analysis["technical"]["indicators"]
        lines.append("#### テクニカル指標")
        lines.append("")
        lines.append("| 指標 | 値 |")
        lines.append("|------|-----|")
        if ind.get("rsi"): lines.append(f"| RSI(14) | {ind['rsi']} |")
        macd = ind.get("macd", {})
        if macd:
            ml = macd.get('line')
            ms = macd.get('signal')
            ml_str = f'{ml:+.0f}' if ml is not None else '-'
            ms_str = f'{ms:+.0f}' if ms is not None else '-'
            lines.append(f"| MACD | {ml_str} / signal {ms_str} |")
        if ind.get("bollinger", {}).get("position_pct"): lines.append(f"| BB位置 | {ind['bollinger']['position_pct']}% |")
        if ind.get("sma_25"): lines.append(f"| 25日SMA | {_yen(ind['sma_25'])} |")
        if ind.get("sma_75"): lines.append(f"| 75日SMA | {_yen(ind['sma_75'])} |")
        if ind.get("atr"): lines.append(f"| ATR | {_yen(ind['atr'])} |")
        if ind.get("volatility_annual_pct"): lines.append(f"| 年換算ボラ | {ind['volatility_annual_pct']}% |")
        lines.append("")

    # Scenarios
    if analysis and analysis.get("fundamental", {}).get("scenarios"):
        lines.append("#### シナリオ")
        lines.append("")
        lines.append("| シナリオ | 株価 | 確率 |")
        lines.append("|----------|------|------|")
        for s in analysis["fundamental"]["scenarios"]:
            lines.append(f"| {s['label']} | {_yen(s.get('price'))} | {s['probability']*100:.0f}% |")
        lines.append("")

    # Investment thesis
    thesis = analysis.get("fundamental", {}).get("investment_thesis", "") if analysis else ""
    if thesis:
        lines.append("#### 投資仮説")
        lines.append("")
        lines.append(thesis)
        lines.append("")

    # Triggers
    triggers = action.get("triggers", [])
    if triggers:
        lines.append("#### 監視トリガー")
        lines.append("")
        for t in triggers:
            lines.append(f"- {t}")
        lines.append("")

    lines.append("---")
    lines.append("")


def _format_forecast_row(fc: dict) -> str:
    """Format forecast OHLC as a Markdown table row with confidence."""
    if fc.get("confidence") == "unavailable":
        reason = fc.get("unavailable_reason", "")
        return f"4本値目安: データ不足（{reason}）"

    ohlc = fc.get("ohlc") or {}
    o, h, l, c = ohlc.get("open"), ohlc.get("high"), ohlc.get("low"), ohlc.get("close")
    conf = fc.get("confidence", "low")
    lines = [
        "| 始値 | 高値 | 安値 | 終値 | 確度 |",
        "|------|------|------|------|------|",
        f"| {_yen(o)} | {_yen(h)} | {_yen(l)} | {_yen(c)} | {conf} |",
        "",
    ]
    bp = fc.get("base_price")
    atr = fc.get("inputs", {}).get("atr")
    if bp and atr:
        lines.append(f"- ベース価格: {_yen(bp)} / ATR: {_yen(atr)}")
    bias = fc.get("bias")
    if bias:
        lines.append(f"- バイアス: {bias.get('direction','?')} / {bias.get('strength','?')}")
    reasoning = fc.get("reasoning")
    if reasoning:
        lines.append(f"- 根拠: {reasoning}")
    return "\n".join(lines)


def _esc(text: str) -> str:
    """Escape pipe characters in Markdown table cells."""
    if text is None:
        return ""
    return str(text).replace("|", "\\|")


def _yen(value) -> str:
    if value is None:
        return "-"
    try:
        return f"¥{int(value):,}"
    except (ValueError, TypeError):
        return str(value)
