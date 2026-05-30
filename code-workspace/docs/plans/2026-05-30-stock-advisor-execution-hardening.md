# Stock Advisor Execution Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `stock-advisor` reliably executable without manual shell fixes, manual report validation iterations, or source/mirror confusion.

**Architecture:** Add a deterministic numeric pipeline runner, harden tests and validators, fix artifact shape mismatches, and update skill instructions to use the runner. Keep report generation LLM-assisted, but make all pre-report artifacts and validation deterministic.

**Tech Stack:** Python 3.14, pytest, YAML/JSON artifacts, existing stock-advisor scripts under `/Users/fujie/.dotfiles/claude/skills/stock-advisor`.

---

## Current Findings From The 2026-05-30 Run

1. Test command was not reproducible without `PYTHONPATH`.
   - Running from `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts`:
     `scripts/.venv/bin/pytest tests/test_quant_schema.py ...`
   - Failed with `ModuleNotFoundError: No module named 'quant_schema'`.
   - Workaround was `PYTHONPATH=. .venv/bin/pytest ...`.

2. Backtest loop in `SKILL.md` is unsafe under zsh.
   - The first loop passed all tickers as one argument to `--ticker`.
   - `backtest_engine.py` then tried to load `"1328.T 1515.T ..."` as a ticker and failed with `KeyError: ['Date']`.
   - Root cause: command substitution + zsh word splitting assumptions.

3. Backtest produced noisy warnings for watchlist tickers.
   - Warnings: `RuntimeWarning: invalid value encountered in divide` and `ConstantInputWarning`.
   - JSON files were created, but logs made it hard to distinguish real failures from non-fatal statistical warnings.

4. `report_context.json` loses macro context.
   - `signals.json` has macro data inside each result under `macro`.
   - `report_context_builder.py` reads only `signals_data.get("macro_context", {})`, so `macro_context` becomes `{}`.

5. `validate_report.py` has useful strictness but false positives for metadata words.
   - It rejected `open_date`.
   - It would also reject metadata such as `quant_decisions`, `risk_posture`, or `advisory_plan` unless the report avoids those words.
   - The root cause is that the validator treats every lowercase underscored token as a possible invented signal.

6. Position-count validation is too regex-dependent.
   - Group headings like `### 7974.T 任天堂 — 3ポジション（銘柄全体 -13.1%）` were counted as position headings.
   - The report had 11 real positions but the check counted 13 until group headings were manually adjusted.

7. Skill source/mirror is confusing.
   - Current source used by execution is `/Users/fujie/.claude/skills/stock-advisor/SKILL.md`, backed by `/Users/fujie/.dotfiles/claude/skills/stock-advisor`.
   - The skill path advertised to this Codex session was `/Users/fujie/.agents/skills/stock-advisor/SKILL.md`, which is stale and still includes the older portfolio-fetch/deep-analyze flow.

8. Report writing is still too manual.
   - The numeric pipeline is deterministic.
   - The final report required hand-written content, then validator-driven edits.
   - This is acceptable for a human-readable report, but the system needs a deterministic report skeleton so the LLM is refining a safe draft instead of constructing structure from scratch.

## File Responsibility Map

- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/conftest.py`
  - Ensure all tests can import script modules without `PYTHONPATH`.
- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/run_stock_advisor_pipeline.py`
  - Run signal generation, per-ticker backtests, portfolio analytics, quant decisions, and report context generation with safe subprocess calls.
- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_run_stock_advisor_pipeline.py`
  - Test ticker collection and command construction without hitting network.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`
  - Extract macro context from top-level `macro_context` or first available per-ticker `macro`.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`
  - Assert macro context is exported.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py`
  - Add metadata-token allowlist.
  - Add optional `--portfolio` position-count validation.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`
  - Cover metadata words and position-count validation.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/backtest_engine.py`
  - Suppress or avoid constant-input correlation warnings by checking variance before `spearmanr`.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_backtest_engine.py`
  - Add a constant-series IC test.
- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_skeleton_builder.py`
  - Generate a validator-friendly Markdown skeleton from `report_context.json`.
- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_skeleton_builder.py`
  - Ensure the skeleton passes validator and has the same position count as `portfolio.yaml`.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`
  - Replace shell loops with the new runner.
- Modify `/Users/fujie/.agents/skills/stock-advisor/SKILL.md`
  - Mark it as a runtime mirror and point to `/Users/fujie/.claude/skills/stock-advisor/SKILL.md`, or sync the current source content exactly.

## Task 1: Fix Pytest Import Reliability

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/conftest.py`

- [ ] **Step 1: Add failing reproduction command**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_schema.py -q
```

Expected before fix:

```text
ModuleNotFoundError: No module named 'quant_schema'
```

- [ ] **Step 2: Add `conftest.py`**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/conftest.py`:

```python
import os
import sys


SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
```

- [ ] **Step 3: Verify tests run without `PYTHONPATH`**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_schema.py tests/test_quant_decision_engine.py tests/test_report_context_builder.py tests/test_validate_report.py -q
```

Expected:

```text
36 passed
```

- [ ] **Step 4: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/conftest.py
git -C /Users/fujie/.dotfiles commit -m "test: fix stock advisor import path"
```

## Task 2: Add A Safe Numeric Pipeline Runner

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/run_stock_advisor_pipeline.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_run_stock_advisor_pipeline.py`

- [ ] **Step 1: Add unit tests for ticker collection**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_run_stock_advisor_pipeline.py`:

```python
import pathlib

from run_stock_advisor_pipeline import collect_tickers


def test_collect_tickers_combines_holdings_and_watchlist(tmp_path):
    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text(
        """
holdings:
  - ticker: 1515.T
  - ticker: 285A.T
  - ticker: 1515.T
""".strip()
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        """
- ticker: 7203.T
- ticker: 285A.T
""".strip()
    )

    assert collect_tickers(portfolio, watchlist) == ["1515.T", "285A.T", "7203.T"]


def test_collect_tickers_works_without_watchlist(tmp_path):
    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\\n  - ticker: 5803.T\\n")
    watchlist = tmp_path / "missing.yaml"

    assert collect_tickers(portfolio, watchlist) == ["5803.T"]
```

- [ ] **Step 2: Implement runner**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/run_stock_advisor_pipeline.py`:

```python
#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

import yaml


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
VENV_PYTHON = SCRIPTS_DIR / ".venv" / "bin" / "python"
DEFAULT_PORTFOLIO = pathlib.Path.home() / "code" / "playground" / "stock-price-analyze" / "portfolio.yaml"
DEFAULT_RESULTS_ROOT = pathlib.Path.home() / "code" / "playground" / "stock-price-analyze" / "results"
DEFAULT_WATCHLIST = pathlib.Path.home() / ".claude" / "skills" / "stock-advisor" / "watchlist.yaml"


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def collect_tickers(portfolio_path: pathlib.Path, watchlist_path: pathlib.Path) -> list[str]:
    portfolio = yaml.safe_load(portfolio_path.read_text()) or {}
    seen = {}
    for holding in portfolio.get("holdings", []):
        ticker = holding.get("ticker")
        if ticker:
            seen[ticker] = None

    if watchlist_path.exists():
        watchlist = yaml.safe_load(watchlist_path.read_text()) or []
        for item in watchlist:
            if isinstance(item, dict) and item.get("ticker"):
                seen[item["ticker"]] = None

    return sorted(seen)


def read_reference_date(signals_path: pathlib.Path) -> str:
    signals = json.loads(signals_path.read_text())
    reference_date = signals.get("reference_date")
    if not reference_date:
        raise RuntimeError(f"signals.json has no reference_date: {signals_path}")
    return reference_date


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stock-advisor numeric pipeline")
    parser.add_argument("--portfolio", type=pathlib.Path, default=DEFAULT_PORTFOLIO)
    parser.add_argument("--watchlist", type=pathlib.Path, default=DEFAULT_WATCHLIST)
    parser.add_argument("--results-dir", type=pathlib.Path)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results_dir = args.results_dir or DEFAULT_RESULTS_ROOT / args.date
    backtest_dir = results_dir / "backtest"
    results_dir.mkdir(parents=True, exist_ok=True)
    backtest_dir.mkdir(parents=True, exist_ok=True)
    latest = DEFAULT_RESULTS_ROOT / "latest"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(results_dir, target_is_directory=True)

    signals_path = results_dir / "signals.json"
    run([str(SCRIPTS_DIR / "run_signal_engine"), "--all", "--output", str(signals_path)])

    reference_date = read_reference_date(signals_path)
    tickers = collect_tickers(args.portfolio, args.watchlist)
    for ticker in tickers:
        run([
            str(VENV_PYTHON),
            str(SCRIPTS_DIR / "backtest_engine.py"),
            "--ticker", ticker,
            "--strategy", "default",
            "--execution-delay",
            "--end", reference_date,
            "-o", str(backtest_dir / f"{ticker}.json"),
        ])

    analytics_path = results_dir / "portfolio_analytics.json"
    run([
        str(VENV_PYTHON),
        str(SCRIPTS_DIR / "portfolio_analytics.py"),
        "--portfolio", str(args.portfolio),
        "-o", str(analytics_path),
    ])

    decisions_path = results_dir / "quant_decisions.json"
    run([
        str(VENV_PYTHON),
        str(SCRIPTS_DIR / "quant_decision_engine.py"),
        "--portfolio", str(args.portfolio),
        "--signals", str(signals_path),
        "--backtest-dir", str(backtest_dir),
        "--portfolio-analytics", str(analytics_path),
        "-o", str(decisions_path),
    ])

    context_path = results_dir / "report_context.json"
    run([
        str(VENV_PYTHON),
        str(SCRIPTS_DIR / "report_context_builder.py"),
        "--portfolio", str(args.portfolio),
        "--signals", str(signals_path),
        "--backtest-dir", str(backtest_dir),
        "--portfolio-analytics", str(analytics_path),
        "--quant-decisions", str(decisions_path),
        "-o", str(context_path),
    ])

    manifest = {
        "results_dir": str(results_dir),
        "reference_date": reference_date,
        "tickers": tickers,
        "artifacts": {
            "signals": str(signals_path),
            "backtest_dir": str(backtest_dir),
            "portfolio_analytics": str(analytics_path),
            "quant_decisions": str(decisions_path),
            "report_context": str(context_path),
        },
    }
    (results_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Make runner executable**

Run:

```bash
chmod +x /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/run_stock_advisor_pipeline.py
```

- [ ] **Step 4: Run tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_run_stock_advisor_pipeline.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/run_stock_advisor_pipeline.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_run_stock_advisor_pipeline.py
git -C /Users/fujie/.dotfiles commit -m "feat: add stock advisor pipeline runner"
```

## Task 3: Preserve Macro Context In Report Context

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`

- [ ] **Step 1: Add failing macro test**

Append to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`:

```python
def test_macro_context_is_exported_from_per_ticker_macro():
    context = _run_builder()
    macro = context["macro_context"]
    assert macro["vix"]["value"] == 15.32
    assert macro["sp500"]["change_pct"] == 0.22
    assert macro["usdjpy"]["value"] == 159.27
    assert macro["us10y"]["value"] == 4.45
```

Update `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/signals.json` so at least one result contains:

```json
      "macro": {
        "vix": {"ticker": "^VIX", "value": 15.32, "change_pct": -2.67},
        "sp500": {"ticker": "^GSPC", "value": 7580.06, "change_pct": 0.22},
        "usdjpy": {"ticker": "JPY=X", "value": 159.27, "change_pct": -0.19},
        "us10y": {"ticker": "^TNX", "value": 4.45, "change_pct": -0.04}
      }
```

- [ ] **Step 2: Implement macro extraction**

Add this function to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`:

```python
def build_macro_context(signals_data: dict) -> dict:
    if signals_data.get("macro_context"):
        return signals_data["macro_context"]
    for entry in signals_data.get("results", []):
        macro = entry.get("macro")
        if isinstance(macro, dict) and macro:
            return macro
    return {}
```

Replace:

```python
        "macro_context": signals_data.get("macro_context", {}),
```

with:

```python
        "macro_context": build_macro_context(signals_data),
```

- [ ] **Step 3: Run tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_report_context_builder.py -q
```

Expected: all report context tests pass.

- [ ] **Step 4: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/signals.json
git -C /Users/fujie/.dotfiles commit -m "fix: preserve stock report macro context"
```

## Task 4: Harden Report Validator Without Losing Signal Protection

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`

- [ ] **Step 1: Add metadata allowlist tests**

Append to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`:

```python
def test_accepts_known_metadata_tokens():
    report = """\
285A.T 一部売却
5803.T 一部売却
open_date expiry_date quant_decisions risk_posture advisory_plan
委託保証金率 1124.46%
"""
    result = _run_validator(report)
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Add metadata token allowlist**

In `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py`, add near the top:

```python
KNOWN_METADATA_TOKENS = {
    "open_date",
    "expiry_date",
    "quant_decisions",
    "report_context",
    "risk_posture",
    "advisory_plan",
    "protective_stop_price",
    "portfolio_weight_pct",
    "cost_basis_weight_pct",
    "unrealized_pnl_pct",
    "downside_10pct_yen",
    "report_action",
    "order_shares",
    "order_type",
    "limit_price",
}
```

Then add this line inside `check_invented_signals()` after `known = _known_signal_rules(signals_path)`:

```python
    known.update(KNOWN_METADATA_TOKENS)
```

- [ ] **Step 3: Run validator tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_validate_report.py -q
```

Expected: validator tests pass.

- [ ] **Step 4: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py
git -C /Users/fujie/.dotfiles commit -m "fix: allow stock report metadata tokens"
```

## Task 5: Add Position Count Validation To Validator

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`

- [ ] **Step 1: Add position-count tests**

Append to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`:

```python
def test_rejects_wrong_position_count(tmp_path):
    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\\n  - ticker: 285A.T\\n  - ticker: 5803.T\\n")
    report = tmp_path / "report.md"
    report.write_text("### 285A.T キオクシアHD — HOLD（+335.1%）\\n")

    result = subprocess.run(
        [
            VENV_PYTHON,
            VALIDATOR,
            "--report", str(report),
            "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
            "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
            "--backtest-dir", os.path.join(FIXTURE_DIR, "backtest"),
            "--portfolio", str(portfolio),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "position count mismatch" in result.stderr
```

- [ ] **Step 2: Implement optional portfolio validation**

Add imports:

```python
import yaml
```

Add this helper:

```python
def check_position_count(report_text: str, portfolio_path: str | None) -> str | None:
    if not portfolio_path:
        return None
    with open(portfolio_path) as f:
        portfolio = yaml.safe_load(f) or {}
    expected = len(portfolio.get("holdings", []))
    actual = len(re.findall(r"^(#### .+|### .+ — .+（[-+0-9.]+%）)$", report_text, re.MULTILINE))
    if actual != expected:
        return f"position count mismatch: portfolio={expected}, report={actual}"
    return None
```

Update `validate()` signature:

```python
def validate(report_path: str, signals_path: str, quant_decisions_path: str, backtest_dir: str, portfolio_path: str | None = None) -> list[str]:
```

Call the helper before returning errors:

```python
    err = check_position_count(report_text, portfolio_path)
    if err:
        errors.append(err)
```

Add parser argument:

```python
    parser.add_argument("--portfolio", help="Optional portfolio.yaml path for position-count validation")
```

Pass it into `validate(...)`.

- [ ] **Step 3: Run validator tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_validate_report.py -q
```

Expected: all validator tests pass.

- [ ] **Step 4: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py
git -C /Users/fujie/.dotfiles commit -m "feat: validate stock report position count"
```

## Task 6: Reduce Noisy Backtest Warnings For Constant Series

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/backtest_engine.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_backtest_engine.py`

- [ ] **Step 1: Locate current `spearmanr` call**

Run:

```bash
rg -n "spearmanr|ConstantInputWarning|ic_results" /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/backtest_engine.py
```

Expected: find the `spearmanr(s, fw)` block around the IC calculation.

- [ ] **Step 2: Add constant series helper**

Add near the IC code:

```python
def _safe_spearmanr(signal_values, forward_returns) -> tuple[float | None, float | None]:
    if len(signal_values) < 2 or len(forward_returns) < 2:
        return None, None
    if len(set(signal_values)) <= 1 or len(set(forward_returns)) <= 1:
        return None, None
    ic, pval = spearmanr(signal_values, forward_returns)
    return float(ic), float(pval)
```

Replace direct `spearmanr(s, fw)` usage with `_safe_spearmanr(s, fw)`.

- [ ] **Step 3: Add unit test**

Add to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_backtest_engine.py`:

```python
def test_safe_spearmanr_returns_none_for_constant_input():
    from backtest_engine import _safe_spearmanr

    ic, pval = _safe_spearmanr([1, 1, 1], [0.01, 0.02, 0.03])
    assert ic is None
    assert pval is None
```

- [ ] **Step 4: Run backtest tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_backtest_engine.py -q
```

Expected: backtest tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/backtest_engine.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_backtest_engine.py
git -C /Users/fujie/.dotfiles commit -m "fix: avoid constant input warnings in backtest"
```

## Task 7: Add Deterministic Report Skeleton Builder

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_skeleton_builder.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_skeleton_builder.py`

- [ ] **Step 1: Add skeleton smoke test**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_skeleton_builder.py`:

```python
import os
import subprocess
import tempfile


SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(SCRIPTS_DIR, ".venv", "bin", "python")
BUILDER = os.path.join(SCRIPTS_DIR, "report_skeleton_builder.py")
FIXTURE_DIR = os.path.join(SCRIPTS_DIR, "tests", "fixtures", "report_quality")


def test_skeleton_builder_outputs_required_sections():
    with tempfile.TemporaryDirectory() as tmpdir:
        context = os.path.join(tmpdir, "report_context.json")
        report = os.path.join(tmpdir, "report.md")
        subprocess.run(
            [
                PYTHON,
                os.path.join(SCRIPTS_DIR, "report_context_builder.py"),
                "--portfolio", os.path.join(FIXTURE_DIR, "portfolio.yaml"),
                "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
                "--backtest-dir", os.path.join(FIXTURE_DIR, "backtest"),
                "--portfolio-analytics", os.path.join(FIXTURE_DIR, "portfolio_analytics.json"),
                "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
                "-o", context,
            ],
            check=True,
        )
        subprocess.run([PYTHON, BUILDER, "--context", context, "-o", report], check=True)
        text = open(report).read()

    assert "## 株式分析" in text
    assert "## 取引指示一覧" in text
    assert "## 銘柄別詳細" in text
    assert "## 本日の優先アクション" in text
```

- [ ] **Step 2: Implement skeleton builder**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_skeleton_builder.py`:

```python
#!/usr/bin/env python3
import argparse
import json
import os


def yen(value) -> str:
    if value is None:
        return "-"
    return f"¥{float(value):,.0f}"


def action_ja(action: str) -> str:
    return {
        "BUY": "追加買い",
        "HOLD": "保有継続",
        "REDUCE": "一部売却",
        "SELL": "全株売却",
        "NO_TRADE": "取引なし",
    }.get(action, action)


def build_report(context: dict) -> str:
    account = context["account"]
    decisions = context["quant_decisions"]["decisions"]
    lines = [
        f"## 株式分析 {context.get('reference_date', '')}",
        "",
        "### 総括",
        f"- 評価額 {yen(account.get('total_assets'))}、現金 {yen(account.get('available_cash'))}、{account.get('margin_ratio_label')} {account.get('margin_ratio_text')}",
        "",
        "---",
        "",
        "## 取引指示一覧",
        "",
        "| # | Ticker | アクション | 数量 | 注文種別 | 執行タイミング | 指値/成行価格 | 目標価格 | ストップロス | 根拠 |",
        "|---|--------|-----------|------|---------|--------------|------------|---------|------------|------|",
    ]
    row_no = 1
    for ticker, decision in decisions.items():
        if decision["report_action"] not in ("REDUCE", "SELL", "BUY") or decision.get("order_shares", 0) == 0:
            continue
        lines.append(
            f"| {row_no} | {ticker} | {action_ja(decision['report_action'])} | {decision['order_shares']}株 | {decision['order_type']} | 翌営業日寄付き | {yen(decision.get('limit_price'))} | - | - | {', '.join(decision.get('vetoes', []))} |"
        )
        row_no += 1
    if row_no == 1:
        lines.append("| - | - | 取引なし | 0株 | none | 見送り | - | - | - | actionable orderなし |")

    lines += ["", "---", "", "## 銘柄別詳細", ""]
    for holding in context["holdings"]:
        ticker = holding["ticker"]
        decision = decisions.get(ticker, {"report_action": "HOLD", "order_shares": 0})
        qty = holding.get("quantity", 0)
        current = holding.get("current_price")
        cost = holding.get("cost_price")
        pnl_pct = ((float(current) - float(cost)) / float(cost) * 100) if current and cost else 0
        lines += [
            f"### {ticker} {holding.get('name', '')}（{holding.get('position_type', '現物')}） — {decision['report_action']}（{pnl_pct:+.1f}%）",
            "",
            "| 項目 | 値 |",
            "|------|-----|",
            f"| 現在値 | {yen(current)}（取得 {yen(cost)} × {qty}株） |",
            f"| リスク姿勢 | {decision.get('risk_posture', 'neutral')} |",
            f"| 防衛ライン | {yen(decision.get('protective_stop_price'))} |",
            f"| 10%下落影響 | {yen(decision.get('downside_10pct_yen'))} |",
            "",
            "**判断**",
            f"- アクション: **{action_ja(decision['report_action'])}**",
            f"- 数量: **{decision.get('order_shares', 0)}株**",
            f"- 理由: {', '.join(decision.get('vetoes', [])) or 'no actionable signal'}",
            "",
        ]

    lines += [
        "---",
        "",
        "## 本日の優先アクション",
        "",
    ]
    if row_no == 1:
        lines.append("1. **[監視] 全銘柄**: 本日の即時売買なし。")
    else:
        lines.append("1. **[実行] 取引指示一覧**: 上記の注文を優先。")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build validator-friendly stock report skeleton")
    parser.add_argument("--context", required=True)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    with open(args.context) as f:
        context = json.load(f)
    report = build_report(context)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(report)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run skeleton test**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_report_skeleton_builder.py -q
```

Expected: skeleton test passes.

- [ ] **Step 4: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_skeleton_builder.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_skeleton_builder.py
git -C /Users/fujie/.dotfiles commit -m "feat: add stock report skeleton builder"
```

## Task 8: Update Skill Instructions And Runtime Mirror

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`
- Modify: `/Users/fujie/.agents/skills/stock-advisor/SKILL.md`

- [ ] **Step 1: Replace manual numeric pipeline commands**

In `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`, replace Step 1 through Step 2e command blocks with:

```markdown
### Step 1: 数値パイプライン実行

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/run_stock_advisor_pipeline.py \
  --portfolio ~/code/playground/stock-price-analyze/portfolio.yaml \
  --watchlist ~/.claude/skills/stock-advisor/watchlist.yaml
```

出力された `run_manifest.json` の `artifacts` を確認し、`signals.json`、`backtest/*.json`、`portfolio_analytics.json`、`quant_decisions.json`、`report_context.json` が存在することを確認する。
```

- [ ] **Step 2: Add skeleton generation command**

In the same file, add before report generation:

```markdown
### Step 2: レポート骨子生成

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/report_skeleton_builder.py \
  --context ~/code/playground/stock-price-analyze/results/$(date +%F)/report_context.json \
  -o ~/code/playground/stock-price-analyze/results/$(date +%F)/report.md
```

LLMはこの `report.md` を整える。アクション、数量、シグナル名、WF判定、口座ラベルは変更しない。
```

- [ ] **Step 3: Update validator command**

Update the validator command in `SKILL.md` to pass `--portfolio`:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/validate_report.py \
  --report "$RESULTS_DIR/report.md" \
  --signals "$RESULTS_DIR/signals.json" \
  --quant-decisions "$RESULTS_DIR/quant_decisions.json" \
  --backtest-dir "$RESULTS_DIR/backtest" \
  --portfolio ~/code/playground/stock-price-analyze/portfolio.yaml
```

- [ ] **Step 4: Fix runtime mirror**

Replace `/Users/fujie/.agents/skills/stock-advisor/SKILL.md` with:

```markdown
---
name: stock-advisor
description: Runtime mirror notice for stock-advisor. Source of truth is ~/.claude/skills/stock-advisor/SKILL.md.
---

# stock-advisor runtime mirror

This runtime mirror is intentionally thin.

Use `/Users/fujie/.claude/skills/stock-advisor/SKILL.md` as the source of truth for the current stock-advisor workflow.
Do not edit this file for workflow changes.
```

- [ ] **Step 5: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md
git -C /Users/fujie/.dotfiles commit -m "docs: simplify stock advisor execution flow"
```

If `/Users/fujie/.agents` is not git-managed, leave the runtime mirror change uncommitted and record it in the final implementation summary.

## Task 9: End-To-End Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run unit tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest \
  tests/test_quant_schema.py \
  tests/test_quant_decision_engine.py \
  tests/test_report_context_builder.py \
  tests/test_validate_report.py \
  tests/test_run_stock_advisor_pipeline.py \
  tests/test_report_skeleton_builder.py \
  tests/test_backtest_engine.py \
  -q
```

Expected: all selected tests pass without `PYTHONPATH`.

- [ ] **Step 2: Run numeric pipeline**

Run:

```bash
/Users/fujie/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  /Users/fujie/.claude/skills/stock-advisor/scripts/run_stock_advisor_pipeline.py \
  --portfolio /Users/fujie/code/playground/stock-price-analyze/portfolio.yaml \
  --watchlist /Users/fujie/.claude/skills/stock-advisor/watchlist.yaml \
  --date 2026-05-30
```

Expected:

```text
run_manifest.json written
```

and the manifest lists 10 tickers.

- [ ] **Step 3: Generate skeleton and validate**

Run:

```bash
RESULTS_DIR=/Users/fujie/code/playground/stock-price-analyze/results/2026-05-30
/Users/fujie/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  /Users/fujie/.claude/skills/stock-advisor/scripts/report_skeleton_builder.py \
  --context "$RESULTS_DIR/report_context.json" \
  -o "$RESULTS_DIR/report.md"
/Users/fujie/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  /Users/fujie/.claude/skills/stock-advisor/scripts/validate_report.py \
  --report "$RESULTS_DIR/report.md" \
  --signals "$RESULTS_DIR/signals.json" \
  --quant-decisions "$RESULTS_DIR/quant_decisions.json" \
  --backtest-dir "$RESULTS_DIR/backtest" \
  --portfolio /Users/fujie/code/playground/stock-price-analyze/portfolio.yaml
```

Expected: validator exits with code 0.

- [ ] **Step 4: Confirm critical decisions**

Run:

```bash
python3 - <<'PY'
import json
d=json.load(open('/Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/quant_decisions.json'))
for t in ['285A.T','1515.T','5803.T']:
    x=next(i for i in d['decisions'] if i['ticker']==t)
    print(t, x['action'], x['order_shares'], x.get('risk_posture'), x.get('advisory_plan'))
PY
```

Expected:

```text
285A.T HOLD 0 protect_profit {...}
1515.T HOLD 0 rebalance_on_strength {...}
5803.T REDUCE 300 neutral {}
```

- [ ] **Step 5: Review git state**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short --branch
```

Expected: clean working tree on the implementation branch after commits.

## Self-Review

- Spec coverage: The plan covers the test import failure, shell loop failure, noisy backtest warnings, missing macro context, validator false positives, position-count validation, manual report skeleton issue, and stale runtime mirror.
- Simplicity review: The plan does not rewrite the quant model. It hardens execution around the model already implemented by Claude Code.
- Security review: No SBI Cookie, credentials, or session data are added. Generated results remain under ignored result directories.
- Git review: Source changes belong in `/Users/fujie/.dotfiles`. Runtime generated artifacts under `/Users/fujie/code/playground/stock-price-analyze/results` should remain uncommitted unless explicitly curated as fixtures.
