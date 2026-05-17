#!/usr/bin/env python3
"""deep-analyze パイプライン起動スクリプト。

TradingAgents v0.2.5 日本語対応版パイプラインを実行し、
構造化された判断を出力する。

使い方:
  python run_deep_analyze.py <TICKER> [--output-dir <dir>]
"""

import argparse
import json
import os
import sys
from datetime import date

TRADING_VENV = os.path.expanduser("~/code/deepcode/TradingAgents/.venv/bin/python3")
STOCK_VENV = os.path.expanduser("~/code/playground/stock-price-analyze/.venv/bin/python3")

if os.path.isfile(TRADING_VENV) and sys.executable != TRADING_VENV:
    os.execv(TRADING_VENV, [TRADING_VENV] + sys.argv)
elif os.path.isfile(STOCK_VENV) and sys.executable != STOCK_VENV:
    os.execv(STOCK_VENV, [STOCK_VENV] + sys.argv)

# Add pipeline dir to path for adapters import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adapters import build_config, run_pipeline, format_decision_output, load_previous_memory


def main():
    parser = argparse.ArgumentParser(description="deep-analyze マルチエージェント分析")
    parser.add_argument("ticker", help="分析対象ティッカー (例: 7203.T)")
    parser.add_argument("--output-dir", help="出力ディレクトリ")
    parser.add_argument("--language", default="Japanese", help="出力言語 (default: Japanese)")
    args = parser.parse_args()

    config = build_config(args.ticker, output_language=args.language)
    if args.output_dir:
        config["output_dir"] = args.output_dir

    print(f"## deep-analyze: {args.ticker}")
    print(f"Language: {config['output_language']}")
    print(f"Deep Think: {config['deep_think']}")
    print()

    prev = load_previous_memory(args.ticker)
    if prev:
        print(f"[INFO] 過去の分析メモリが見つかりました（{len(prev)} chars）")
        config["previous_context"] = prev
    print()

    result = run_pipeline(config)

    print(format_decision_output(result))

    os.makedirs(config["output_dir"], exist_ok=True)
    output_path = os.path.join(config["output_dir"], "decision.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"Output saved to {output_path}")


if __name__ == "__main__":
    main()
