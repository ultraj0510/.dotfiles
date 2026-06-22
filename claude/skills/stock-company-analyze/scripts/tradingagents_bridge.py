"""Bridge between stock-company-analyze and TradingAgents fork."""
import json
import time
from pathlib import Path

AGENT_TIMEOUT = 600
TOTAL_TIMEOUT = 3600
MAX_RETRIES = 2


def build_config(evidence_pack_path, market_metrics_path, run_dir):
    return {
        "llm_provider": "anthropic",
        "deep_think_llm": "claude-sonnet-4-6",
        "quick_think_llm": "claude-sonnet-4-6",
        "temperature": None,
        "max_debate_rounds": 2,
        "max_risk_discuss_rounds": 0,
        "output_language": "Japanese",
        "checkpoint_enabled": True,
        "data_cache_dir": str(run_dir / "checkpoints"),
        "evidence_pack_path": str(evidence_pack_path),
        "market_metrics_path": str(market_metrics_path),
        "data_vendors": {},
        "news_article_limit": 0,
        "global_news_article_limit": 0,
    }


def validate_agent_outputs(outputs):
    errors = []
    for agent_name, output in outputs.items():
        if not isinstance(output, dict):
            errors.append(f"{agent_name}: output is not dict")
            continue
        for claim in output.get("claims", []):
            if claim.get("claim_type") == "fact" and not claim.get("evidence_ids"):
                errors.append(f"{agent_name}: fact '{str(claim.get('claim_ja', ''))[:40]}' missing evidence_ids")
        for inf in output.get("inferences", []):
            if inf.get("claim_type") == "inference" and not inf.get("reason_ja"):
                errors.append(f"{agent_name}: inference '{str(inf.get('claim_ja', ''))[:40]}' missing reason_ja")
    return errors


def run_analysis(evidence_pack_path, market_metrics_path, run_dir, config_overrides=None):
    config = build_config(evidence_pack_path, market_metrics_path, run_dir)
    if config_overrides:
        config.update(config_overrides)
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
    except ImportError as e:
        return {"error": f"TradingAgents not installed: {e}", "status": "failed"}

    pack = json.loads(Path(evidence_pack_path).read_text())
    ticker = pack["ticker"]
    date_str = pack["as_of"][:10]

    ta = TradingAgentsGraph(debug=False, config=config)
    start = time.monotonic()
    try:
        final_state, result = ta.propagate(ticker, date_str)
    except Exception as e:
        return {"error": str(e), "status": "failed"}
    elapsed = time.monotonic() - start
    # result is the structured dict from _build_result_dict:
    # {"analyst_reports": {...}, "debate": {...}, "portfolio_manager": {...}}
    return {
        "status": "completed",
        "result": result,
        "elapsed_seconds": round(elapsed, 1),
        "config": {k: v for k, v in config.items() if "key" not in k.lower()},
    }
