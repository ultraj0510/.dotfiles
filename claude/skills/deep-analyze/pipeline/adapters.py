"""LLM-based adapter for deep-analyze (TradingAgents replacement).

Runs stock-advisor pipeline modules for a single ticker and
produces a report_context.json for Claude to interpret.
"""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

STOCK_ADVISOR_SCRIPTS = os.path.expanduser(
    "~/.dotfiles/claude/skills/stock-advisor/scripts"
)
STOCK_VENV_PYTHON = os.path.join(STOCK_ADVISOR_SCRIPTS, ".venv", "bin", "python")


def build_config(ticker: str, output_language: str = "Japanese") -> dict:
    """Build analysis configuration for a single ticker."""
    output_dir = os.path.expanduser(
        f"~/.claude/skills/stock-advisor/_workspace/{ticker}/{date.today().isoformat()}"
    )
    return {
        "ticker": ticker,
        "output_language": output_language,
        "output_dir": output_dir,
        "deep_think": True,
    }


def load_previous_memory(ticker: str) -> str | None:
    """Load previous analysis memory if available."""
    memory_file = os.path.expanduser(
        f"~/.claude/skills/stock-advisor/_workspace/{ticker}/memory.json"
    )
    if os.path.isfile(memory_file):
        try:
            with open(memory_file) as f:
                data = json.load(f)
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return None


def run_pipeline(config: dict) -> dict:
    """Run stock-advisor pipeline modules for a single ticker."""
    ticker = config["ticker"]
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {"ticker": ticker, "steps_completed": [], "errors": []}

    def _run(cmd: list[str], step_name: str):
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
            results["steps_completed"].append(step_name)
        except subprocess.CalledProcessError as e:
            results["errors"].append(f"{step_name}: {e.stderr[:500]}")
        except Exception as e:
            results["errors"].append(f"{step_name}: {str(e)[:500]}")

    # Step 1: Signal engine (single ticker)
    signals_path = output_dir / "signals.json"
    _run(
        [
            STOCK_VENV_PYTHON,
            os.path.join(STOCK_ADVISOR_SCRIPTS, "signal_engine.py"),
            "--ticker", ticker,
            "-o", str(signals_path),
        ],
        "signal_engine",
    )

    # Step 2: Backtest
    backtest_dir = output_dir / "backtest"
    backtest_dir.mkdir(exist_ok=True)
    reference_date = date.today().isoformat()
    if signals_path.exists():
        try:
            with open(signals_path) as f:
                ref = json.load(f).get("reference_date", "")
            if ref:
                reference_date = ref
        except Exception:
            pass

    _run(
        [
            STOCK_VENV_PYTHON,
            os.path.join(STOCK_ADVISOR_SCRIPTS, "backtest_engine.py"),
            "--ticker", ticker,
            "--strategy", "auto",
            "--execution-delay",
            "--end", reference_date,
            "-o", str(backtest_dir / f"{ticker}.json"),
        ],
        "backtest",
    )

    # Step 3: Price zones (single ticker)
    zones_path = output_dir / "price_zones_and_margin.json"
    tick_sizes_path = os.path.join(
        os.path.dirname(STOCK_ADVISOR_SCRIPTS), "data", "tick_sizes.json"
    )
    price_limits_path = os.path.join(
        os.path.dirname(STOCK_ADVISOR_SCRIPTS), "data", "price_limits.json"
    )
    market_conv_path = os.path.join(
        os.path.dirname(STOCK_ADVISOR_SCRIPTS), "market_conventions.yaml"
    )
    portfolio_path = os.path.expanduser(
        "~/code/playground/stock-price-analyze/portfolio.yaml"
    )

    _run(
        [
            STOCK_VENV_PYTHON,
            os.path.join(STOCK_ADVISOR_SCRIPTS, "price_zone_calculator.py"),
            "--ticker", ticker,
            "--signals", str(signals_path),
            "--portfolio", portfolio_path,
            "--tick-sizes", tick_sizes_path,
            "--price-limits", price_limits_path,
            "--market-conventions", market_conv_path,
            "-o", str(zones_path),
        ],
        "price_zones",
    )

    # Step 4: Peer comparison
    peer_output = output_dir / "peer_comparison.json"
    peer_mapping_path = os.path.join(
        os.path.dirname(STOCK_ADVISOR_SCRIPTS), "peer_mapping.yaml"
    )
    jp_stop_limit_pct = -30.0
    if zones_path.exists():
        try:
            with open(zones_path) as f:
                zones_data = json.load(f)
            jp_stop_limit_pct = zones_data.get("stop_limit_pct", -30.0)
        except Exception:
            pass

    jp_close = 0
    if signals_path.exists():
        try:
            with open(signals_path) as f:
                sig_data = json.load(f)
            for entry in sig_data.get("results", []):
                if entry["ticker"] == ticker:
                    jp_close = float(entry.get("indicators", {}).get("close", 0))
                    break
        except Exception:
            pass

    if jp_close > 0:
        _run(
            [
                STOCK_VENV_PYTHON,
                os.path.join(STOCK_ADVISOR_SCRIPTS, "peer_comparison.py"),
                "--ticker", ticker,
                "--jp-close", str(jp_close),
                "--jp-stop-limit-pct", str(round(jp_stop_limit_pct, 2)),
                "--peer-mapping", peer_mapping_path,
                "-o", str(peer_output),
            ],
            "peer_comparison",
        )

    # Save context
    context = {
        "ticker": ticker,
        "reference_date": reference_date,
        "generated_at": date.today().isoformat(),
        "signals": None,
        "backtest": None,
        "price_zones": None,
        "peer_comparison": None,
        "steps_completed": results["steps_completed"],
        "errors": results["errors"],
    }

    if signals_path.exists():
        with open(signals_path) as f:
            context["signals"] = json.load(f)
    if zones_path.exists():
        with open(zones_path) as f:
            context["price_zones"] = json.load(f)
    if peer_output.exists():
        with open(peer_output) as f:
            context["peer_comparison"] = json.load(f)

    context_path = output_dir / "report_context.json"
    with open(context_path, "w") as f:
        json.dump(context, f, ensure_ascii=False, indent=2, default=str)

    # Save memory
    memory_path = output_dir.parent / "memory.json"
    memory = {
        "ticker": ticker,
        "last_analysis": date.today().isoformat(),
        "last_decision": {},
    }
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    with open(memory_path, "w") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

    return context


def format_decision_output(result: dict) -> str:
    """Format pipeline results as FINAL_DECISION."""
    lines = [
        "## FINAL_DECISION",
        "",
        f"**Ticker:** {result.get('ticker', '?')}",
        f"**Reference Date:** {result.get('reference_date', '?')}",
        f"**Steps Completed:** {', '.join(result.get('steps_completed', []))}",
    ]
    errors = result.get("errors", [])
    if errors:
        lines.append("")
        lines.append("**Errors:**")
        for e in errors:
            lines.append(f"- {e}")
    lines.append("")
    lines.append("> LLM deep analysis follows in report.md")
    return "\n".join(lines)
