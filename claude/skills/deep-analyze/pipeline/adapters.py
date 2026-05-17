"""Claude Code エージェントと TradingAgents パイプラインのアダプタ。

TradingAgents の LangGraph パイプラインを Claude Code スキルから
呼び出すためのインターフェース。
"""

import os
import sys
import json
from pathlib import Path
from datetime import date

TRADING_AGENTS_DIR = os.path.expanduser("~/code/deepcode/TradingAgents")
if TRADING_AGENTS_DIR not in sys.path:
    sys.path.insert(0, TRADING_AGENTS_DIR)


def build_config(ticker: str, output_language: str = "Japanese") -> dict:
    """TradingAgents の設定を構築する。

    v0.2.5 対応: 全7エージェントが output_language を尊重。
    DeepSeek V4 互換のため DeepSeekChatOpenAI を使用。
    """
    return {
        "ticker": ticker,
        "output_language": output_language,
        "deep_think": os.environ.get("TRADINGAGENTS_DEEP_THINK", "false").lower() == "true",
        "max_debate_rounds": int(os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "2")),
        "memory_log_dir": os.environ.get(
            "TRADINGAGENTS_MEMORY_LOG_DIR",
            os.path.expanduser("~/.claude/skills/stock-advisor/_workspace/memory"),
        ),
        "output_dir": os.path.expanduser(
            f"~/.claude/skills/stock-advisor/_workspace/{ticker}/{date.today().isoformat()}"
        ),
    }


def load_previous_memory(ticker: str) -> str | None:
    """同一 ticker の過去判断を memory log から読み込む。

    v0.2.5 の _resolve_pending_entries() → reflection ライフサイクルを使用。
    """
    try:
        from tradingagents.agents.utils.memory import TradingMemoryLog

        memory_dir = os.path.expanduser("~/.claude/skills/stock-advisor/_workspace/memory")
        log = TradingMemoryLog(memory_dir)
        entries = log._resolve_pending_entries(ticker)
        if entries:
            return entries
    except ImportError:
        pass
    return None


def run_pipeline(config: dict) -> dict:
    """TradingAgents のフルパイプラインを実行する。

    パイプライン構成:
    - 4 analysts (market/fundamentals/sentiment/news)
    - bull/bear debate (research manager 統括)
    - trader (トレードプラン生成)
    - 3-way risk debate (bull/bear/neutral)
    - portfolio manager (最終判断 + PortfolioDecision)
    """
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.agents.utils.agent_utils import get_language_instruction

    lang_instruction = get_language_instruction(config["output_language"])

    graph = TradingAgentsGraph(
        ticker=config["ticker"],
        output_language=config["output_language"],
        deep_think=config["deep_think"],
        max_debate_rounds=config["max_debate_rounds"],
        previous_context=config.get("previous_context"),
    )

    result = graph.run()

    return {
        "ticker": config["ticker"],
        "decision": result.get("decision", {}),
        "research_plan": result.get("research_plan", {}),
        "trader_proposal": result.get("trader_proposal", {}),
        "debate_log": result.get("debate_log", []),
        "memory_updated": result.get("memory_updated", False),
    }


def format_decision_output(result: dict) -> str:
    """パイプライン結果を stock-advisor 互換の FINAL_DECISION 形式に整形。"""
    decision = result.get("decision", {})
    if not decision:
        return ""

    lines = [
        "## FINAL_DECISION",
        "",
        f"**Ticker:** {result['ticker']}",
        f"**Action:** {decision.get('action', 'HOLD')}",
        f"**Quantity:** {decision.get('quantity', 0)}株",
        f"**Entry Price:** ¥{decision.get('entry_price', 0):,}",
        f"**Stop Loss:** ¥{decision.get('stop_loss', 0):,}",
        f"**Take Profit:** ¥{decision.get('take_profit', 0):,}",
        f"**Confidence:** {decision.get('confidence', 'medium')}",
        "",
        f"**Rationale:** {decision.get('rationale', '')}",
        f"**Risk Factors:** {decision.get('risk_factors', '')}",
        "",
    ]

    trader = result.get("trader_proposal", {})
    if trader:
        lines.append("### Trade Plan")
        lines.append(f"- Entry Strategy: {trader.get('entry_strategy', 'N/A')}")
        lines.append(f"- Exit Strategy: {trader.get('exit_strategy', 'N/A')}")
        lines.append(f"- Position Sizing: {trader.get('position_sizing', 'N/A')}")
        lines.append("")

    return "\n".join(lines)
