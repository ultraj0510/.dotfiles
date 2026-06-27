"""Phase 4 LLM analysis engine."""
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from prompt_context import build_prompt_context
from llm_provider import LLMProvider


def validate_analysis_output(output: dict[str, Any]) -> bool:
    """TradingAgents-compatible output structure validation. Raises ValueError on failure."""
    if "analyst_reports" not in output:
        raise ValueError("Missing 'analyst_reports' in output")
    if "portfolio_manager" not in output:
        raise ValueError("Missing 'portfolio_manager' in output")

    pm = output["portfolio_manager"]
    scenarios = pm.get("scenarios", [])
    if len(scenarios) != 3:
        raise ValueError(f"Expected 3 scenarios, got {len(scenarios)}")

    for s in scenarios:
        for key in ("label", "eps", "per", "probability"):
            if key not in s:
                raise ValueError(f"Scenario missing '{key}': {s}")

    if not pm.get("investment_thesis_ja"):
        raise ValueError("Missing 'investment_thesis_ja' in portfolio_manager")

    probs = [s["probability"] for s in scenarios]
    prob_sum = sum(probs)
    if abs(prob_sum - 1.0) > 0.01:
        raise ValueError(
            f"Scenario probabilities sum to {prob_sum}, expected 1.0"
        )

    return True


def _build_prompt(
    company_name: str,
    ticker: str,
    reference_date: str,
    context: dict[str, Any],
) -> str:
    """Build analysis prompt from prompt_context output. Uses string.Template-style
    substitution (no Jinja2 dependency)."""

    lines: list[str] = []

    # Header
    lines.append("## 分析対象")
    lines.append(f"- 企業: {company_name}")
    lines.append(f"- ティッカー: {ticker}")
    lines.append(f"- 基準日: {reference_date}")
    cp = context.get("current_price")
    lines.append(f"- 現在株価: {'¥{:,}'.format(int(cp)) if cp else 'データなし'}")
    lines.append("")

    # Company profile
    lines.append("## 会社概要")
    profile = context.get("company_profile", {})
    if profile:
        for key, val in profile.items():
            lines.append(f"- {key}: {val}")
    else:
        lines.append("会社概要データなし")
    lines.append("")

    # Performance
    lines.append("## 業績データ")
    perf = context.get("performance", [])
    if perf:
        for item in perf:
            lines.append(f"- {item['field']}: {item['value']}")
    else:
        lines.append("業績データなし")
    lines.append("")

    # Technical indicators
    lines.append("## テクニカル指標（直近取引日）")
    m = context.get("latest_market", {})
    _add_indicator(lines, "RSI(14)", m.get("rsi"))
    _add_indicator(lines, "25日SMA", m.get("sma_25"), fmt="{:,.0f}")
    _add_indicator(lines, "75日SMA", m.get("sma_75"), fmt="{:,.0f}")
    _add_indicator(lines, "対25SMA乖離", m.get("price_vs_sma25_pct"), fmt="{:+.1f}%")
    _add_indicator(lines, "対75SMA乖離", m.get("price_vs_sma75_pct"), fmt="{:+.1f}%")
    _add_indicator(lines, "BB上限", m.get("bollinger_upper"), fmt="{:,.0f}")
    _add_indicator(lines, "BB中央", m.get("bollinger_middle"), fmt="{:,.0f}")
    _add_indicator(lines, "BB下限", m.get("bollinger_lower"), fmt="{:,.0f}")
    _add_indicator(lines, "BB位置", m.get("bollinger_position_pct"), fmt="{:.1f}%")
    _add_indicator(lines, "MACDライン", m.get("macd_line"), fmt="{:,.1f}")
    _add_indicator(lines, "MACDシグナル", m.get("macd_signal"), fmt="{:,.1f}")
    _add_indicator(lines, "MACDヒストグラム", m.get("macd_histogram"), fmt="{:,.1f}")
    _add_indicator(lines, "年換算ボラティリティ", m.get("volatility_annual_pct"), fmt="{:.1f}%")
    _add_indicator(lines, "最大ドローダウン", m.get("max_drawdown_pct"), fmt="{:.1f}%")
    _add_indicator(lines, "20日リターン", m.get("return_20d_pct"), fmt="{:+.1f}%")
    _add_indicator(lines, "出来高対平均比", m.get("volume_ratio_vs_avg"), fmt="{:.2f}x")
    lines.append("")

    # IR documents
    lines.append("## 直近IR資料")
    ir_docs = context.get("ir_documents", [])
    if ir_docs:
        for doc in ir_docs[:10]:
            lines.append(
                f"- {doc.get('published_at', '?' )} [{doc.get('field', '')}] {doc.get('title', '')}"
            )
    else:
        lines.append("IR資料なし")
    lines.append("")

    # Company scores
    scores = context.get("company_scores", {})
    if scores:
        lines.append("## 企業スコア")
        for key, val in scores.items():
            lines.append(f"- {key}: {val}")
        lines.append("")

    # Data quality
    dq = context.get("data_quality", {})
    lines.append("## データ品質")
    lines.append(f"- データ鮮度: {dq.get('price_freshness_hours', 'N/A')}時間前")
    counts = context.get("evidence_counts", {})
    count_str = ", ".join(f"{k}={v}" for k, v in counts.items())
    lines.append(f"- エビデンス件数: {count_str or 'N/A'}")
    lines.append("")

    # Instructions
    lines.append("## 指示")
    lines.append("以下の役割を順に実行し、最終的に指定されたJSONスキーマで出力してください。")
    lines.append("")
    lines.append("### 1. Bull Researcher（強気アナリスト）")
    lines.append("入手可能なデータから強気シナリオを構築し、少なくとも3つの根拠を挙げてください。")
    lines.append("各根拠には、evidence_idまたは具体的なデータポイントを引用してください。")
    lines.append("")
    lines.append("### 2. Bear Researcher（弱気アナリスト）")
    lines.append("入手可能なデータから弱気シナリオを構築し、少なくとも3つのリスク・反証を挙げてください。")
    lines.append("各反証には、evidence_idまたは具体的なデータポイントを引用してください。")
    lines.append("")
    lines.append("### 3. Portfolio Manager（ポートフォリオマネージャー）")
    lines.append("Bull/Bearの分析を踏まえ、以下を決定してください:")
    lines.append("- **proposed_rating**: BUY / HOLD / SELL / SHORT / NOT_RATED")
    lines.append("- **investment_thesis_ja**: 日本語での投資判断サマリー（3-5文）")
    lines.append("- **scenarios**: 以下の3シナリオをEPS×PERで算出")
    lines.append("  - 強気シナリオ（確率 0.2〜0.5）")
    lines.append("  - 中立シナリオ（確率 0.2〜0.6）")
    lines.append("  - 弱気シナリオ（確率 0.1〜0.4）")
    lines.append("  - 確率の合計は必ず 1.0 にすること")
    lines.append("- **catalysts**: 今後3-12ヶ月のポジティブカタリスト（2-4件）")
    lines.append("- **disconfirmers**: 投資判断を覆しうるリスク要因（2-4件）")
    lines.append("- **monitoring_triggers**: 再評価すべきイベント（2-4件）")
    lines.append("- **data_gaps**: 判断に不足しているデータ（1-3件）")
    lines.append("")
    lines.append("出力は以下に示す JSON スキーマに厳密に従ってください。")
    lines.append("Markdownコードブロック（```json）で囲まず、純粋なJSONオブジェクトのみを返してください。")

    return "\n".join(lines)


def _add_indicator(
    lines: list[str],
    label: str,
    value: Any,
    fmt: str | None = None,
) -> None:
    if value is None:
        lines.append(f"- {label}: N/A")
    elif fmt:
        lines.append(f"- {label}: {fmt.format(value)}")
    else:
        lines.append(f"- {label}: {value}")


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["analyst_reports", "debate", "portfolio_manager"],
    "properties": {
        "analyst_reports": {
            "type": "object",
            "required": ["bull_researcher", "bear_researcher"],
            "properties": {
                "bull_researcher": {"type": "object"},
                "bear_researcher": {"type": "object"},
            },
        },
        "debate": {"type": "object"},
        "portfolio_manager": {
            "type": "object",
            "required": ["proposed_rating", "scenarios", "investment_thesis_ja"],
            "properties": {
                "proposed_rating": {
                    "type": "string",
                    "enum": ["BUY", "HOLD", "SELL", "SHORT", "NOT_RATED"],
                },
                "investment_thesis_ja": {"type": "string"},
                "scenarios": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "required": ["label", "eps", "per", "probability"],
                        "properties": {
                            "label": {"type": "string"},
                            "eps": {"type": "number"},
                            "per": {"type": "number"},
                            "probability": {"type": "number"},
                        },
                    },
                },
                "catalysts": {"type": "array", "items": {"type": "string"}},
                "disconfirmers": {"type": "array", "items": {"type": "string"}},
                "monitoring_triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "data_gaps": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


def run_llm_analysis(
    evidence_pack_path: Path,
    market_metrics_path: Path,
    run_dir: Path,
    provider: LLMProvider,
) -> dict[str, Any]:
    """Run Phase 4 LLM analysis, returning a TradingAgents-compatible result dict."""
    evidence_pack = json.loads(Path(evidence_pack_path).read_text())
    market_metrics = json.loads(Path(market_metrics_path).read_text())

    ticker = evidence_pack.get("ticker", "")
    company_name = evidence_pack.get("company_name", ticker)
    reference_date = evidence_pack.get("as_of", "")

    context = build_prompt_context(evidence_pack, market_metrics)
    prompt = _build_prompt(company_name, ticker, reference_date, context)

    result = provider.analyze(
        prompt=prompt,
        schema=OUTPUT_SCHEMA,
        context=context,
        evidence_pack=evidence_pack,
        market_metrics=market_metrics,
        company_name=company_name,
        ticker=ticker,
        run_dir=run_dir,
    )

    if result.get("status") == "completed":
        validate_analysis_output(result["result"])

        # Save raw LLM output for FileProvider / debugging
        llm_result_path = run_dir / "llm-analysis-result.json"
        _atomic_write(
            llm_result_path,
            json.dumps(result["result"], ensure_ascii=False, indent=2),
        )

    return result


def _atomic_write(path: Path, data: str) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)
