#!/usr/bin/env python3
"""Generate self-contained Japanese HTML report from analysis.json."""
import html as html_mod
import json
from pathlib import Path
from report_validator import validate_for_report, extract_sections


def _esc(text):
    if text is None:
        return ""
    return html_mod.escape(str(text))


def _fmt_price(value):
    if value is None:
        return "—"
    return f"{int(value):,}"


def _fmt_pct(value):
    if value is None:
        return "—"
    return f"{value * 100:+.1f}%"


def _tag(kind):
    labels = {
        "fact": ("reported", "確認済"),
        "inference": ("derived", "分析"),
        "judgment": ("judgment", "判断"),
        "unknown": ("missing", "未確認"),
    }
    cls, text = labels.get(kind, ("", kind))
    return f'<span class="tag {cls}">{text}</span>'


def _render_claims(claims):
    if not claims:
        return ""
    items = ""
    for c in claims:
        kind = c.get("claim_type", "fact")
        text = c.get("claim_ja", c.get("claim_en", ""))
        eids = c.get("evidence_ids", [])
        links = " ".join(f'<code style="font-size:10px">[{_esc(e[:8])}]</code>' for e in eids[:3])
        items += f"<li>{_tag(kind)} {_esc(text)} {links}</li>"
    return f"<ul>{items}</ul>"


CSS = """<style>
:root { --ink: #172022; --muted: #657073; --paper: #f4f1ea; --panel: #fffdfa; --line: #d8d3c9; --blue: #244f64; --teal: #16746b; --red: #a5483f; --amber: #a66a16; --soft-blue: #e8f0f3; --soft-teal: #e6f1ee; --soft-red: #f5e8e5; --soft-amber: #f6eddc; }
* { box-sizing: border-box; }
body { margin: 0; color: var(--ink); background: var(--paper); font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic", system-ui, sans-serif; line-height: 1.65; }
a { color: var(--blue); text-decoration-thickness: 1px; text-underline-offset: 3px; }
.page { max-width: 1180px; margin: 0 auto; padding: 28px 32px 72px; }
.hero { padding: 38px 42px; color: #f7faf9; background: linear-gradient(135deg, #102a35 0%, #1e5260 60%, #16746b 100%); border-radius: 18px; box-shadow: 0 18px 45px rgba(19, 39, 45, .17); }
.eyebrow { margin: 0 0 8px; font-size: 13px; letter-spacing: .12em; text-transform: uppercase; opacity: .78; }
h1 { margin: 0; font-size: clamp(30px, 5vw, 52px); line-height: 1.18; letter-spacing: -.035em; }
.subtitle { margin: 10px 0 26px; font-size: 18px; opacity: .86; }
.verdict { display: grid; grid-template-columns: 1.2fr .8fr; gap: 26px; align-items: end; padding-top: 24px; border-top: 1px solid rgba(255,255,255,.24); }
.verdict strong { display: block; font-size: 27px; line-height: 1.35; }
.badge { display: inline-flex; align-items: center; width: fit-content; padding: 7px 12px; border-radius: 999px; font-weight: 700; font-size: 13px; background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25); }
.hero-price { text-align: right; }
.hero-price .value { display: block; font-size: 40px; font-weight: 800; line-height: 1.1; }
.hero-price .asof { font-size: 13px; opacity: .74; }
.grid { display: grid; gap: 16px; }
.metrics { grid-template-columns: repeat(4, 1fr); margin-top: 18px; }
.metric, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 8px 24px rgba(28, 39, 41, .045); }
.metric { padding: 19px 20px; }
.metric .label { color: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: .04em; }
.metric .number { display: block; margin: 4px 0 1px; font-size: 25px; font-weight: 800; line-height: 1.2; }
.metric .note { color: var(--muted); font-size: 12px; }
.section { margin-top: 38px; }
h2 { margin: 0 0 15px; font-size: 25px; letter-spacing: -.025em; }
h3 { margin: 0 0 9px; font-size: 18px; }
.panel { padding: 24px; }
.two { grid-template-columns: 1fr 1fr; }
.bull { border-top: 5px solid var(--teal); }
.bear { border-top: 5px solid var(--red); }
.neutral { border-top: 5px solid var(--amber); }
ul { margin: 10px 0 0; padding-left: 1.25em; }
li + li { margin-top: 8px; }
.tag { display: inline-block; margin-right: 6px; padding: 2px 7px; border-radius: 5px; font-size: 11px; font-weight: 800; vertical-align: 1px; }
.reported { color: #0d6059; background: var(--soft-teal); }
.derived { color: #315c6e; background: var(--soft-blue); }
.judgment { color: #865414; background: var(--soft-amber); }
.missing { color: #8a3d36; background: var(--soft-red); }
.gate { width: 100%; border-collapse: collapse; font-size: 14px; }
.gate th, .gate td { padding: 12px 13px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }
.gate th { color: var(--muted); font-size: 12px; letter-spacing: .035em; }
.status { white-space: nowrap; font-weight: 800; }
.ok { color: var(--teal); }
.warn { color: var(--amber); }
.no { color: var(--red); }
.scenario { padding: 22px; }
.scenario .case { display: flex; justify-content: space-between; gap: 15px; align-items: baseline; }
.scenario .target { font-size: 27px; font-weight: 800; }
.scenario .return { font-weight: 800; }
.scenario .bar { height: 8px; margin: 14px 0; border-radius: 10px; background: #e8e4dc; overflow: hidden; }
.scenario .fill { height: 100%; border-radius: inherit; }
.timeline { position: relative; margin-left: 8px; padding-left: 28px; border-left: 2px solid var(--line); }
.event { position: relative; padding: 0 0 22px; }
.event:last-child { padding-bottom: 0; }
.event:before { content: ""; position: absolute; left: -35px; top: 6px; width: 12px; height: 12px; border-radius: 50%; background: var(--blue); border: 3px solid var(--paper); }
.event .date { color: var(--blue); font-size: 12px; font-weight: 800; }
.rules { counter-reset: rule; list-style: none; padding: 0; margin: 0; }
.rules li { counter-increment: rule; position: relative; padding: 15px 15px 15px 52px; border-bottom: 1px solid var(--line); }
.rules li:last-child { border-bottom: 0; }
.rules li:before { content: counter(rule); position: absolute; left: 12px; top: 14px; display: grid; place-items: center; width: 26px; height: 26px; color: white; background: var(--blue); border-radius: 50%; font-size: 12px; font-weight: 800; }
.sources { font-size: 13px; }
.sources li { overflow-wrap: anywhere; }
.footnote { margin-top: 28px; padding: 18px 20px; color: var(--muted); background: rgba(255,255,255,.48); border-left: 4px solid var(--amber); font-size: 13px; }
@media (max-width: 820px) { .page { padding: 16px 16px 48px; } .hero { padding: 28px 24px; } .verdict, .two, .three { grid-template-columns: 1fr; } .metrics { grid-template-columns: 1fr 1fr; } .hero-price { text-align: left; } }
@media (max-width: 500px) { .metrics { grid-template-columns: 1fr; } }
</style>"""


def generate_html(analysis):
    errors = validate_for_report(analysis)
    if errors:
        raise ValueError(f"Invalid analysis.json: {'; '.join(errors)}")
    s = extract_sections(analysis)
    sec = []

    provisional_badge = '<span class="badge" style="background:var(--soft-amber);color:var(--amber);margin-left:10px">暫定</span>' if s.provisional else ""
    hero_price = f'<span class="value">¥{_fmt_price(s.current_price)}</span><span class="asof">{_esc(s.as_of[:10])} 基準</span>' if s.current_price else ""
    adj = f"PM原案 {_esc(s.pm_proposal)} から補正" if s.adjusted else "PM原案と一致"

    # Section 2
    sec.append(f'<section class="section"><h2>現在株価と期待リターン</h2><div class="grid metrics"><div class="metric"><span class="label">現在株価</span><span class="number">¥{_fmt_price(s.current_price)}</span></div><div class="metric"><span class="label">12か月期待価格</span><span class="number">¥{_fmt_price(s.expected_price)}</span></div><div class="metric"><span class="label">期待リターン</span><span class="number">{_fmt_pct(s.expected_return)}</span></div><div class="metric"><span class="label">confidence</span><span class="number">{_esc(s.confidence_level)}</span><span class="note">{s.confidence_score}/100</span></div></div></section>')

    # Section 3: Bull/Bear
    if s.analyst_reports:
        sec.append('<section class="section"><h2>強気・弱気の主要論点</h2><div class="grid two">')
        for side, cls in [("bull", "bull"), ("bear", "bear")]:
            report = s.analyst_reports.get(f"{side}_researcher", {})
            summary = report.get("summary_ja", "")
            if summary:
                sec.append(f'<div class="panel {cls}"><h3>{"強気" if side == "bull" else "弱気"}派</h3><p>{_esc(summary)}</p></div>')
        sec.append('</div></section>')

    # Section 4: Market expectations
    market = s.analyst_reports.get("market_analyst", {}) if s.analyst_reports else {}
    if market.get("summary_ja"):
        sec.append(f'<section class="section"><h2>市場が織り込んでいる期待</h2><div class="panel neutral"><p>{_esc(market.get("summary_ja", ""))}</p>{_render_claims(market.get("claims", []))}</div></section>')

    # Section 5: Implementation gate
    gate = f'<tr><td>データカバレッジ</td><td><span class="status {"ok" if s.data_quality_complete else "warn"}">{"完全" if s.data_quality_complete else "不完全"}</span></td><td>{"IR公式サイト全件確認済" if s.data_quality_complete else "一部動的E-IR未取得"}</td></tr>'
    gate += f'<tr><td>SHORT実装可否</td><td><span class="status {"ok" if s.short_eligible else "no"}">{"可能" if s.short_eligible else "不可"}</span></td><td>{"全ゲート充足" if s.short_eligible else "借株料・空売り残高・踏み上げリスク未確認"}</td></tr>'
    gate += f'<tr><td>暫定判断</td><td><span class="status {"warn" if s.provisional else "ok"}">{"暫定" if s.provisional else "本判断"}</span></td><td>{"; ".join(s.provisional_reasons) if s.provisional_reasons else "十分な証拠あり"}</td></tr>'
    sec.append(f'<section class="section"><h2>実装可否ゲート</h2><table class="gate"><thead><tr><th>条件</th><th>状態</th><th>詳細</th></tr></thead><tbody>{gate}</tbody></table></section>')

    # Section 6: Scenarios
    if s.scenarios:
        rows = ""
        for sc in s.scenarios:
            price = s.scenario_prices.get(sc["label"], sc.get("eps", 0) * sc.get("per", 0))
            ret = (price / s.current_price - 1) if s.current_price else 0
            emoji = {"bull": "強気", "base": "基本", "bear": "弱気"}.get(sc["label"], "")
            rows += f'<div class="scenario panel"><div class="case"><strong>{emoji}</strong><span class="target">¥{_fmt_price(price)}</span><span class="return">{_fmt_pct(ret)}</span><span>{sc.get("probability", 0) * 100:.0f}%</span></div><div class="bar"><div class="fill" style="width:{sc.get("probability", 0) * 100:.0f}%;background:var(--{"teal" if sc["label"] == "bull" else "blue" if sc["label"] == "base" else "red"})"></div></div><p>EPS ¥{_fmt_price(sc.get("eps", 0))} · PER {sc.get("per", 0):.0f}x · {_esc(sc.get("rationale_ja", ""))}</p></div>'
        sec.append(f'<section class="section"><h2>Bull / Base / Bear シナリオ</h2>{rows}</section>')

    # Section 7: Catalysts
    if s.catalysts:
        items = "".join(f'<div class="event"><span class="date">⏳</span><p>{_esc(c)}</p></div>' for c in s.catalysts)
        sec.append(f'<section class="section"><h2>6か月以内のカタリスト</h2><div class="timeline">{items}</div></section>')

    # Section 8: Disconfirmers
    if s.disconfirmers:
        items = "".join(f"<li>{_esc(d)}</li>" for d in s.disconfirmers)
        sec.append(f'<section class="section"><h2>反証条件</h2><ol class="rules">{items}</ol></section>')

    # Section 9: Action discipline
    if s.final_rating != "NOT_RATED":
        actions = {"BUY": "期待リターン+20%以上が維持され、反証条件が発生しない限り候補", "HOLD": "カタリストまたは決算による明確な方向性確認まで待機", "SELL": "反証条件が解消するか下落カタリストが顕在化するまで保持", "SHORT": "下落カタリストの顕在化、借株料・空売り残高の継続的確認が前提"}
        sec.append(f'<section class="section"><h2>条件付きアクション規律</h2><div class="panel neutral"><p>{_esc(actions.get(s.final_rating, ""))}</p><p style="margin-top:8px;font-size:13px;color:var(--muted)">このレーティングは公開株式の調査判断であり、特定の数量・金額・執行指示を含まない。</p></div></section>')

    # Section 10: Monitoring triggers
    if s.monitoring_triggers:
        items = "".join(f'<div class="event"><span class="date">\U0001f514</span><p>{_esc(m)}</p></div>' for m in s.monitoring_triggers)
        sec.append(f'<section class="section"><h2>監視トリガー</h2><div class="timeline">{items}</div></section>')

    # Section 11: Unknowns
    if s.unknowns:
        items = "".join(f"<li>{_tag('unknown')} {_esc(u)}</li>" for u in s.unknowns)
        sec.append(f'<section class="section"><h2>データ不足・未確認事項</h2><ul>{items}</ul></section>')

    # Section 12: PM audit
    if s.adjusted:
        reasons = "".join(f"<li>{_esc(r)}</li>" for r in s.adjustment_reasons)
        sec.append(f'<section class="section"><h2>PM原案とルール補正の監査欄</h2><div class="panel neutral"><p>PM原案: <strong>{_esc(s.pm_proposal)}</strong> → 最終: <strong>{_esc(s.final_rating)}</strong></p><ul>{reasons}</ul></div></section>')

    # Section 13: Sources
    sec.append(f'<section class="section"><h2>主要ソース</h2><ul class="sources"><li>stock-info-fetch (SBI証券 企業情報)</li><li>stock-price-fetch (Yahoo Finance 株価時系列)</li><li>stock-ir-fetch (企業公式IR文書)</li><li>TradingAgents · {_esc(s.model_id)} · 2往復討論</li><li>evidence-pack SHA: <code>{_esc(s.evidence_pack_sha256[:16])}...</code></li></ul></section>')

    body = "\n".join(sec)

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(s.ticker)} {_esc(s.company_name)} | 投資仮説検証</title>
  {CSS}
</head>
<body>
  <main class="page">
    <header class="hero">
      <p class="eyebrow">Public Equity Working Analysis · TSE {_esc(s.ticker)}</p>
      <h1>{_esc(s.company_name)}</h1>
      <p class="subtitle">{_esc(s.investment_thesis or '')}</p>
      <div class="verdict">
        <div>
          <span class="badge">最終レーティング: {_esc(s.final_rating)}{provisional_badge}</span>
          <strong>期待リターン {_fmt_pct(s.expected_return)} · confidence {_esc(s.confidence_level)}</strong>
          <p>{adj} · {"暫定判断" if s.provisional else "本判断"}</p>
        </div>
        <div class="hero-price">{hero_price}</div>
      </div>
    </header>
    {body}
    <aside class="footnote">本レポートは公開株式に対する6〜12か月の調査レーティングであり、売買の推奨・指示ではない。データ不足がある場合は provisional=true で表示。</aside>
  </main>
</body>
</html>"""


def generate_report(analysis_path, output_dir):
    analysis_path = Path(analysis_path)
    if not analysis_path.exists():
        raise FileNotFoundError(f"Analysis not found: {analysis_path}")
    try:
        analysis = json.loads(analysis_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {analysis_path}: {e}")
    html = generate_html(analysis)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.html"
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser(prog="stock-company-report")
    parser.add_argument("ticker")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("/Users/fujie/code/runtime/stock-company-analysis"))
    args = parser.parse_args()
    path = args.data_dir / args.ticker / "runs" / args.run_id / "analysis.json"
    out = args.data_dir / args.ticker / "reports" / args.run_id
    try:
        result = generate_report(path, out)
        print(f"OK {result}")
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
