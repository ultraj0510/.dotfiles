# Stock Advisor Quant Follow-up Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code実装後に見つかった `quant_decision_engine.py` の相関リスク契約不一致、README未更新、未追跡ファイル整理を修正し、stock-advisorのクオンツ判断パイプラインをコミット可能な状態にする。

**Architecture:** `portfolio_analytics.py` の実出力形式を正として、`quant_decision_engine.py` は `portfolio_analytics.json["correlation"]` 配下だけを読む。回帰テストは実JSON形状で先に失敗させ、修正後に全stock-advisorテストとCLI smokeを通す。

**Tech Stack:** Python 3.14, pytest, JSON, Markdown, git

---

## Diagnosis

### Verified Current State

Fresh verification showed:

```text
~/.claude/skills/stock-advisor/scripts/.venv/bin/python -m pytest -q .../scripts/tests
110 passed, 16 warnings
```

But a targeted check showed the actual `portfolio_analytics.json` shape does not trigger correlation sizing:

```text
actual_shape 1900 []
flat_shape 900 ['correlation_concentration']
```

### Root Cause

`portfolio_analytics.py` writes correlation data under `correlation`:

```python
result["correlation"] = compute_correlation_matrix(tickers)
```

The returned object contains:

```python
{
    "risk_concentration": "high",
    "max_correlation": {"pair": ["7203.T", "8306.T"], "value": 0.9}
}
```

But `quant_decision_engine.py` currently reads only top-level fields:

```python
risk = pa.get("risk_summary", pa.get("risk_concentration", ""))
max_corr = pa.get("max_correlation", pa.get("top_correlation", {}))
```

Therefore, the real output from `portfolio_analytics.py` silently disables `correlation_concentration` and prevents BUY size reduction.

### Secondary Gaps

- `/Users/fujie/.dotfiles/README.md` has not been updated in the current working tree, even though the implementation plan included README verification guidance.
- Many new stock-advisor files are still untracked. A commit can easily miss them unless the staging list is explicit.

---

## File Responsibility Map

- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`
  - Read actual `portfolio_analytics.json["correlation"]` shape.
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`
  - Add failing test for actual nested `correlation` shape.
- Modify: `/Users/fujie/.dotfiles/README.md`
  - Document stock-advisor venv test command if absent.
- Stage new files:
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/portfolio_optimizer.py`
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py`
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/signal_reliability.py`
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_cross_sectional_factors.py`
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_portfolio_optimizer.py`
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py`
  - `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_signal_reliability.py`
  - `/Users/fujie/.dotfiles/code-workspace/docs/plans/2026-05-30-stock-advisor-quant-improvement-plan.md`
  - `/Users/fujie/.dotfiles/code-workspace/docs/plans/2026-05-30-stock-advisor-quant-followup-fixes.md`

---

### Task 1: Preserve Current Work And Confirm Scope

**Files:**
- Read: `/Users/fujie/.dotfiles`

- [ ] **Step 1: Confirm dirty state before editing**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short --branch
```

Expected includes:

```text
 M claude/skills/stock-advisor/SKILL.md
 M claude/skills/stock-advisor/scripts/backtest_engine.py
 M claude/skills/stock-advisor/scripts/factor_engine.py
 M claude/skills/stock-advisor/scripts/tests/test_backtest_engine.py
 M claude/skills/stock-advisor/skills/stock-report/SKILL.md
?? claude/skills/stock-advisor/scripts/portfolio_optimizer.py
?? claude/skills/stock-advisor/scripts/quant_decision_engine.py
?? claude/skills/stock-advisor/scripts/quant_schema.py
?? claude/skills/stock-advisor/scripts/signal_reliability.py
?? claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py
```

- [ ] **Step 2: Confirm baseline tests still pass before the bug fix**

Run:

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests
```

Expected:

```text
110 passed
```

- [ ] **Step 3: Confirm targeted bug reproduction**

Run:

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, '/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts')
from quant_decision_engine import make_decision

portfolio = {
    'account': {'total_assets': 10_000_000, 'available_cash': 5_000_000},
    'holdings': [
        {'ticker': '7203.T', 'quantity': 100, 'current_price': 1000, 'cost_price': 900, 'position_type': '現物'},
        {'ticker': '8306.T', 'quantity': 1200, 'current_price': 1000, 'cost_price': 900, 'position_type': '現物'},
    ],
}
signal = {'action': 'BUY', 'current_price': 1000, 'atr': 20}
backtest = {
    'total_trades': 50,
    'wins': 30,
    'losses': 20,
    'avg_win_pct': 5.0,
    'avg_loss_pct': -2.5,
    'walk_forward': {'sharpe_is': 1.0, 'sharpe_oos': 0.8},
}
portfolio_analytics = {
    'correlation': {
        'risk_concentration': 'high',
        'max_correlation': {'pair': ['7203.T', '8306.T'], 'value': 0.9},
    }
}
decision = make_decision('7203.T', signal, backtest, portfolio, portfolio_analytics)
print(decision.order_shares, decision.vetoes)
PY
```

Expected before fix:

```text
1900 []
```

Expected after fix:

```text
900 ['correlation_concentration']
```

---

### Task 2: Add Failing Regression Test For Actual Portfolio Analytics Shape

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`

- [ ] **Step 1: Add test using real `portfolio_analytics.py` output shape**

Append this test to `TestMakeDecision`:

```python
    def test_actual_portfolio_analytics_shape_triggers_correlation_veto(self):
        signal = {"action": "BUY", "current_price": 1000, "atr": 20}
        bt = {
            "total_trades": 50, "wins": 30, "losses": 20,
            "avg_win_pct": 5.0, "avg_loss_pct": -2.5,
            "walk_forward": {"sharpe_is": 1.0, "sharpe_oos": 0.8},
        }
        pf = make_portfolio(holdings=[
            {"ticker": "7203.T", "quantity": 100, "current_price": 1000, "cost_price": 950, "position_type": "現物"},
            {"ticker": "8306.T", "quantity": 1200, "current_price": 1000, "cost_price": 900, "position_type": "現物"},
        ])
        pa = {
            "correlation": {
                "risk_concentration": "high",
                "max_correlation": {"pair": ["7203.T", "8306.T"], "value": 0.9},
            },
            "stress_test": {},
        }

        d = make_decision("7203.T", signal, bt, pf, pa)

        assert "correlation_concentration" in d.vetoes
        assert d.order_shares == 900
```

- [ ] **Step 2: Run only the new test and verify it fails**

Run:

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py::TestMakeDecision::test_actual_portfolio_analytics_shape_triggers_correlation_veto
```

Expected before fix:

```text
FAILED
```

Failure should show `assert 'correlation_concentration' in []`.

---

### Task 3: Fix Correlation Contract In Quant Decision Engine

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`

- [ ] **Step 1: Add a helper for the actual analytics shape**

Add this helper above `make_decision`:

```python
def _extract_correlation_context(portfolio_analytics: dict) -> tuple[str, list[str]]:
    """Extract correlation risk from portfolio_analytics.py output."""
    correlation = portfolio_analytics.get("correlation", {})
    if not isinstance(correlation, dict):
        return "", []

    risk = correlation.get("risk_concentration", "")
    max_corr = correlation.get("max_correlation", {})
    if not isinstance(max_corr, dict):
        return risk, []

    pair = max_corr.get("pair", [])
    if not isinstance(pair, list):
        pair = []
    return risk, pair
```

- [ ] **Step 2: Replace the current correlation check**

Replace:

```python
    # --- Correlation check ---
    corr_concentration = False
    if pa:
        risk = pa.get("risk_summary", pa.get("risk_concentration", ""))
        if risk == "high" or (isinstance(risk, dict) and risk.get("level") == "high"):
            corr_concentration = True
        # Check if ticker is in max-correlation pair
        max_corr = pa.get("max_correlation", pa.get("top_correlation", {}))
        tickers = max_corr.get("tickers", max_corr.get("pair", []))
        if ticker in tickers:
            corr_concentration = True
```

with:

```python
    # --- Correlation check ---
    corr_concentration = False
    if pa:
        risk, max_corr_pair = _extract_correlation_context(pa)
        if risk == "high":
            corr_concentration = True
        if ticker in max_corr_pair:
            corr_concentration = True
```

This intentionally follows the current producer contract from `portfolio_analytics.py` instead of preserving legacy flat shapes.

- [ ] **Step 3: Run the targeted test**

Run:

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py::TestMakeDecision::test_actual_portfolio_analytics_shape_triggers_correlation_veto
```

Expected after fix:

```text
1 passed
```

---

### Task 4: Add CLI Fixture Test For `quant_decision_engine.py`

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/portfolio.yaml`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/signals.json`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/backtest/7203.T.json`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/portfolio_analytics.json`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`

- [ ] **Step 1: Create fixture portfolio**

Create `portfolio.yaml`:

```yaml
account:
  total_assets: 10000000
  available_cash: 5000000
holdings:
  - ticker: 7203.T
    quantity: 100
    current_price: 1000
    cost_price: 950
    position_type: 現物
  - ticker: 8306.T
    quantity: 1200
    current_price: 1000
    cost_price: 900
    position_type: 現物
```

- [ ] **Step 2: Create fixture signals**

Create `signals.json`:

```json
{
  "results": [
    {
      "ticker": "7203.T",
      "score": {"recommendation": "BUY", "score": 50},
      "signals": [{"type": "BUY", "rule": "momentum", "strength": "strong"}],
      "indicators": {"close": "1000", "atr": "20"}
    }
  ]
}
```

- [ ] **Step 3: Create fixture backtest**

Create `backtest/7203.T.json`:

```json
{
  "baseline": {
    "trade_count": 50,
    "win_rate": 60.0,
    "avg_win_pct": 5.0,
    "avg_loss_pct": -2.5
  },
  "walk_forward": {
    "train_metrics": {"sharpe_ratio": 1.0},
    "test_metrics": {"sharpe_ratio": 0.8},
    "sharpe_diff_pct": 20.0,
    "overfit_detected": false,
    "consensus": {"verdict": "robust", "mean_sharpe": 0.8}
  }
}
```

- [ ] **Step 4: Create fixture portfolio analytics**

Create `portfolio_analytics.json`:

```json
{
  "correlation": {
    "risk_concentration": "high",
    "max_correlation": {"pair": ["7203.T", "8306.T"], "value": 0.9}
  },
  "stress_test": {}
}
```

- [ ] **Step 5: Add CLI test**

Add a test that runs `quant_decision_engine.py` with the fixture and asserts:

```python
assert output["decisions"][0]["ticker"] == "7203.T"
assert "correlation_concentration" in output["decisions"][0]["vetoes"]
assert output["decisions"][0]["order_shares"] == 900
```

- [ ] **Step 6: Run CLI fixture test**

Run:

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py
```

Expected:

```text
all tests passed
```

---

### Task 5: Update README Verification Guidance

**Files:**
- Modify: `/Users/fujie/.dotfiles/README.md`

- [ ] **Step 1: Add stock-advisor venv test command if absent**

Under the README test section, add:

```markdown
stock-advisor のテストは専用 venv 経由で実行する:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q ~/.claude/skills/stock-advisor/scripts/tests
```

system Python には `numpy`, `pandas`, `yfinance` が入っていない場合があるため、stock-advisorの検証では使わない。
```

- [ ] **Step 2: Confirm README mentions venv**

Run:

```bash
rg -n "stock-advisor.*venv|scripts/.venv/bin/python|yfinance" /Users/fujie/.dotfiles/README.md
```

Expected: at least one match in the test section.

---

### Task 6: Run Full Verification

**Files:**
- Verify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts`
- Verify: `/Users/fujie/.dotfiles/README.md`

- [ ] **Step 1: Syntax check all touched Python modules**

Run:

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python -m py_compile \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/signal_engine.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/backtest_engine.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/trade_advisor.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/factor_engine.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/portfolio_analytics.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/signal_reliability.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/portfolio_optimizer.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py
```

Expected: exit code 0.

- [ ] **Step 2: Run all stock-advisor tests**

Run:

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests
```

Expected:

```text
111 passed
```

The exact count may be higher if Task 4 adds more than one test. There must be zero failures.

- [ ] **Step 3: Run CLI smoke**

Run:

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py --help
```

Expected: argparse help text and exit code 0.

- [ ] **Step 4: Confirm ignored runtime files are not staged**

Run:

```bash
git -C /Users/fujie/.dotfiles status --ignored --short -- \
  claude/skills/stock-advisor/scripts/.venv \
  claude/skills/stock-advisor/scripts/__pycache__ \
  claude/skills/stock-advisor/scripts/cache \
  claude/skills/stock-advisor/scripts/tests/__pycache__
```

Expected:

```text
!! claude/skills/stock-advisor/scripts/.venv/
!! claude/skills/stock-advisor/scripts/__pycache__/
!! claude/skills/stock-advisor/scripts/cache/
!! claude/skills/stock-advisor/scripts/tests/__pycache__/
```

---

### Task 7: Stage And Commit Explicitly

**Files:**
- Stage all stock-advisor quant source/test/doc changes
- Stage README update
- Stage plan files

- [ ] **Step 1: Stage explicit files**

Run:

```bash
git -C /Users/fujie/.dotfiles add \
  README.md \
  claude/skills/stock-advisor/SKILL.md \
  claude/skills/stock-advisor/skills/stock-report/SKILL.md \
  claude/skills/stock-advisor/scripts/backtest_engine.py \
  claude/skills/stock-advisor/scripts/factor_engine.py \
  claude/skills/stock-advisor/scripts/portfolio_optimizer.py \
  claude/skills/stock-advisor/scripts/quant_decision_engine.py \
  claude/skills/stock-advisor/scripts/quant_schema.py \
  claude/skills/stock-advisor/scripts/signal_reliability.py \
  claude/skills/stock-advisor/scripts/tests/test_backtest_engine.py \
  claude/skills/stock-advisor/scripts/tests/test_cross_sectional_factors.py \
  claude/skills/stock-advisor/scripts/tests/test_portfolio_optimizer.py \
  claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py \
  claude/skills/stock-advisor/scripts/tests/test_quant_schema.py \
  claude/skills/stock-advisor/scripts/tests/test_signal_reliability.py \
  claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/portfolio.yaml \
  claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/signals.json \
  claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/backtest/7203.T.json \
  claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/portfolio_analytics.json \
  code-workspace/docs/plans/2026-05-30-stock-advisor-quant-improvement-plan.md \
  code-workspace/docs/plans/2026-05-30-stock-advisor-quant-followup-fixes.md
```

- [ ] **Step 2: Verify staged scope**

Run:

```bash
git -C /Users/fujie/.dotfiles diff --cached --name-only
git -C /Users/fujie/.dotfiles status --short
```

Expected: staged files are only the explicit source, test, README, and plan files. Ignored `.venv`, `cache`, and `__pycache__` must not appear as staged.

- [ ] **Step 3: Commit**

Run:

```bash
git -C /Users/fujie/.dotfiles commit -m "feat: add quant decision layer for stock advisor"
```

Expected:

```text
[main <sha>] feat: add quant decision layer for stock advisor
```

## Self-Review

- Spec coverage: This plan addresses the confirmed correlation contract bug, missing README verification guidance, and untracked file staging risk.
- Placeholder scan: All commands and paths are explicit.
- Elegance check: The fix follows the current `portfolio_analytics.py` producer contract and avoids adding compatibility branches for obsolete flat shapes.
