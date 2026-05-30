# Stock Advisor Report Quality Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `stock-advisor` reports faithfully reflect pipeline artifacts, especially `quant_decisions.json`, `signals.json`, backtest walk-forward verdicts, account labels, and position-level risk.

**Architecture:** Add a deterministic report context builder between the quant pipeline and the LLM report writer, then validate generated reports against source artifacts. Keep `quant_decisions.json` as the source of truth for actionable trades, and move any LLM disagreement into a non-actionable manual review caveat.

**Tech Stack:** Python 3.14, pytest, JSON/YAML artifacts, existing `stock-advisor` skill scripts under `/Users/fujie/.dotfiles/claude/skills/stock-advisor`.

---

## Current Findings

The report at `/Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/report.md` is readable, but it is not reliable enough for trading decisions.

- `quant_decisions.json` is overridden in prose:
  - `1515.T`: quant action is `HOLD`, but the report recommends selling 1,000 shares.
  - `285A.T`: quant action is `REDUCE 100`, but the report overrides it to `HOLD`.
  - `5803.T`: quant action is `REDUCE 300`, but the report narrows it to credit-only 100 shares without a position-level quant decision.
- `signals.json` facts are invented or renamed:
  - `285A.T` actual signals are `trend_following`, `momentum`, `overbought`; the report mentions `momentum_rising_80`, `uptrend_bb`, `volume_breakout`.
  - `5803.T` actual signal is `drawdown_stop`; the report mentions `uptrend_bb` and `trend`.
- Backtest walk-forward labels are overstated:
  - `285A.T` actual verdict is `unstable`, but the report calls it robust.
  - `1328.T` and `7974.T` actual verdict is `insufficient_data`, but the report treats them as robust/no-veto.
- Account and macro units are mislabeled:
  - `margin_ratio: 1124.46` should be rendered as `委託保証金率 1124.46%`, not `信用倍率1,124倍`.
  - US10Y `change_pct: -0.04` should not be rendered as `-0.04bp` unless explicitly converted.
- Ticker-level quant decisions are too coarse for mixed spot/margin holdings:
  - `5803.T` and `7974.T` have multiple positions, but `quant_decisions.json` cannot represent which lot to sell or keep.
- Watchlist treatment is implicit:
  - `quant_decisions.json` includes holdings and watchlist tickers, but the report omits watchlist tickers without an explicit section.

## File Responsibility Map

- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py`
  - Add position-level decision structures while keeping the ticker-level `QuantDecision` fields.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`
  - Emit `position_decisions` for each held lot.
  - Replace blunt `position_over_cap` handling with `position_over_cap_watch` or `position_over_cap_reduce`.
- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`
  - Build deterministic `report_context.json` from pipeline artifacts.
  - Normalize signal names, walk-forward labels, account labels, watchlist separation, and manual review caveats.
- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py`
  - Fail generated reports that contradict quant actions, invent signal names, overstate WF verdicts, or use wrong account labels.
- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`
  - Cover the observed 2026-05-30 failure modes with small fixtures.
- Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`
  - Verify the bad report patterns fail and compliant report snippets pass.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/skills/stock-report/SKILL.md`
  - Require report writers to use `report_context.json`, not raw artifact guessing.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`
  - Insert report context generation and validation into the pipeline after `quant_decisions.json`.

## Task 1: Capture Current Failures as Fixtures

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/portfolio.yaml`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/signals.json`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/quant_decisions.json`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/portfolio_analytics.json`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/backtest/285A.T.json`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/backtest/5803.T.json`

- [ ] **Step 1: Create minimal fixture directory**

Run:

```bash
mkdir -p /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/backtest
```

Expected: directory exists.

- [ ] **Step 2: Add portfolio fixture**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/portfolio.yaml`:

```yaml
account:
  total_assets: 19661379
  available_cash: 624634
  margin_ratio: 1124.46
holdings:
  - ticker: 285A.T
    name: キオクシア
    position_type: 現物
    quantity: 300
    cost_price: 2900
    current_price: 2195
  - ticker: 5803.T
    name: フジクラ
    position_type: 現物
    quantity: 200
    cost_price: 4200
    current_price: 4820
  - ticker: 5803.T
    name: フジクラ
    position_type: 信用
    quantity: 100
    cost_price: 5200
    current_price: 4820
    expiry_date: 2026-07-15
watchlist:
  - ticker: 8411.T
    name: みずほFG
```

- [ ] **Step 3: Add signals fixture**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/signals.json`:

```json
{
  "reference_date": "2026-05-29",
  "results": [
    {
      "ticker": "285A.T",
      "score": {"score": 0, "recommendation": "HOLD"},
      "signals": [
        {"type": "BUY", "rule": "trend_following", "strength": "strong"},
        {"type": "BUY", "rule": "momentum", "strength": "moderate"},
        {"type": "SELL", "rule": "overbought", "strength": "moderate"}
      ],
      "indicators": {"close": 2195, "rsi": 72.1, "atr": 80}
    },
    {
      "ticker": "5803.T",
      "score": {"score": -25, "recommendation": "HOLD_SELL"},
      "signals": [
        {"type": "SELL", "rule": "drawdown_stop", "strength": "strong"}
      ],
      "indicators": {"close": 4820, "rsi": 41.2, "atr": 150}
    },
    {
      "ticker": "8411.T",
      "watchlist": true,
      "score": {"score": 0, "recommendation": "HOLD"},
      "signals": [
        {"type": "BUY", "rule": "trend_following", "strength": "strong"}
      ],
      "indicators": {"close": 3180, "rsi": 58.0, "atr": 65}
    }
  ],
  "macro_context": {
    "us10y": {"value": 4.4, "change_pct": -0.04}
  }
}
```

- [ ] **Step 4: Add quant decision fixture**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/quant_decisions.json`:

```json
{
  "generated_at": null,
  "decisions": [
    {
      "ticker": "285A.T",
      "action": "REDUCE",
      "confidence": "moderate",
      "order_shares": 100,
      "order_type": "limit",
      "limit_price": 2195,
      "vetoes": ["position_over_cap"],
      "explanations": ["limit sell 100sh"]
    },
    {
      "ticker": "5803.T",
      "action": "REDUCE",
      "confidence": "moderate",
      "order_shares": 300,
      "order_type": "limit",
      "limit_price": 4820,
      "vetoes": ["negative_walk_forward"],
      "explanations": ["limit sell 300sh"]
    },
    {
      "ticker": "8411.T",
      "action": "HOLD",
      "confidence": "low",
      "order_shares": 0,
      "order_type": "none",
      "limit_price": null,
      "vetoes": ["low_sample"],
      "explanations": ["watchlist only"]
    }
  ]
}
```

- [ ] **Step 5: Add analytics and backtest fixtures**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/portfolio_analytics.json`:

```json
{
  "correlation": {
    "avg_correlation": 0.194,
    "risk_concentration": "low",
    "max_correlation": {"pair": ["8473.T", "8729.T"], "value": 0.47}
  }
}
```

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/backtest/285A.T.json`:

```json
{
  "baseline": {"trade_count": 12, "win_rate": 50, "avg_win_pct": 3.0, "avg_loss_pct": -3.0, "sharpe_ratio": 0.0, "kurtosis": 3.2},
  "walk_forward": {"overfit_detected": false, "consensus": {"verdict": "unstable", "n_passed": 0, "n_total": 4}}
}
```

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/backtest/5803.T.json`:

```json
{
  "baseline": {"trade_count": 18, "win_rate": 44.4, "avg_win_pct": 2.0, "avg_loss_pct": -2.5, "sharpe_ratio": -0.72, "kurtosis": 4.1},
  "walk_forward": {"overfit_detected": true, "consensus": {"verdict": "insufficient_data", "n_passed": 0, "n_total": 4}}
}
```

- [ ] **Step 6: Commit fixture baseline**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality
git -C /Users/fujie/.dotfiles commit -m "test: add stock report quality fixtures"
```

Expected: commit succeeds with only fixture files staged.

## Task 2: Build Deterministic Report Context

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`

- [ ] **Step 1: Write failing tests for exact artifact preservation**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`:

```python
import json
import os
import subprocess
import tempfile


SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(SCRIPTS_DIR, "tests", "fixtures", "report_quality")
PYTHON = os.path.join(SCRIPTS_DIR, ".venv", "bin", "python")
BUILDER = os.path.join(SCRIPTS_DIR, "report_context_builder.py")


def build_context():
    with tempfile.TemporaryDirectory() as tmpdir:
        output = os.path.join(tmpdir, "report_context.json")
        subprocess.run(
            [
                PYTHON,
                BUILDER,
                "--portfolio", os.path.join(FIXTURE_DIR, "portfolio.yaml"),
                "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
                "--backtest-dir", os.path.join(FIXTURE_DIR, "backtest"),
                "--portfolio-analytics", os.path.join(FIXTURE_DIR, "portfolio_analytics.json"),
                "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
                "-o", output,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        with open(output) as f:
            return json.load(f)


def test_preserves_signal_rule_names():
    context = build_context()
    by_ticker = {item["ticker"]: item for item in context["holdings"]}
    assert [s["rule"] for s in by_ticker["285A.T"]["signals"]] == [
        "trend_following",
        "momentum",
        "overbought",
    ]
    assert [s["rule"] for s in by_ticker["5803.T"]["signals"]] == ["drawdown_stop"]


def test_preserves_quant_actions_as_report_actions():
    context = build_context()
    by_ticker = {item["ticker"]: item for item in context["holdings"]}
    assert by_ticker["285A.T"]["report_action"] == "REDUCE"
    assert by_ticker["285A.T"]["order_shares"] == 100
    assert by_ticker["5803.T"]["report_action"] == "REDUCE"
    assert by_ticker["5803.T"]["order_shares"] == 300


def test_account_labels_are_report_ready():
    context = build_context()
    assert context["account"]["margin_ratio_label"] == "委託保証金率"
    assert context["account"]["margin_ratio_text"] == "1124.46%"


def test_watchlist_is_separate_from_holdings():
    context = build_context()
    assert [item["ticker"] for item in context["watchlist"]] == ["8411.T"]
    assert "8411.T" not in [item["ticker"] for item in context["holdings"]]


def test_walk_forward_verdict_is_not_upgraded():
    context = build_context()
    by_ticker = {item["ticker"]: item for item in context["holdings"]}
    assert by_ticker["285A.T"]["walk_forward"]["verdict"] == "unstable"
    assert by_ticker["5803.T"]["walk_forward"]["verdict"] == "insufficient_data"
```

- [ ] **Step 2: Verify tests fail before implementation**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_report_context_builder.py -q
```

Expected: FAIL because `report_context_builder.py` does not exist.

- [ ] **Step 3: Implement `report_context_builder.py`**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`:

```python
#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

import yaml


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_backtest(backtest_dir, ticker):
    path = Path(backtest_dir) / f"{ticker}.json"
    if not path.exists():
        return {}
    return load_json(path)


def signal_map(signals):
    mapped = {}
    for item in signals.get("results", []):
        ticker = item.get("ticker")
        if ticker:
            mapped[ticker] = item
    return mapped


def quant_map(quant):
    return {item["ticker"]: item for item in quant.get("decisions", [])}


def position_id(position, index):
    return f'{position.get("ticker", "")}:{position.get("position_type", "現物")}:{index}'


def normalize_wf(backtest):
    wf = backtest.get("walk_forward", {})
    consensus = wf.get("consensus", {})
    return {
        "verdict": consensus.get("verdict", "missing"),
        "n_passed": consensus.get("n_passed"),
        "n_total": consensus.get("n_total"),
        "overfit_detected": wf.get("overfit_detected"),
    }


def build_context(portfolio, signals, backtest_dir, analytics, quant):
    signals_by_ticker = signal_map(signals)
    quant_by_ticker = quant_map(quant)
    holding_rows = []
    holding_tickers = {h.get("ticker") for h in portfolio.get("holdings", [])}

    for index, holding in enumerate(portfolio.get("holdings", []), start=1):
        ticker = holding["ticker"]
        sig = signals_by_ticker.get(ticker, {})
        decision = quant_by_ticker.get(ticker, {"action": "HOLD", "order_shares": 0, "order_type": "none"})
        bt = load_backtest(backtest_dir, ticker)
        holding_rows.append(
            {
                "position_id": position_id(holding, index),
                "ticker": ticker,
                "name": holding.get("name", ""),
                "position_type": holding.get("position_type", "現物"),
                "quantity": holding.get("quantity", 0),
                "cost_price": holding.get("cost_price"),
                "current_price": sig.get("indicators", {}).get("close", holding.get("current_price")),
                "expiry_date": holding.get("expiry_date"),
                "signals": sig.get("signals", []),
                "score": sig.get("score", {}),
                "report_action": decision.get("action", "HOLD"),
                "order_shares": decision.get("order_shares", 0),
                "order_type": decision.get("order_type", "none"),
                "limit_price": decision.get("limit_price"),
                "vetoes": decision.get("vetoes", []),
                "walk_forward": normalize_wf(bt),
            }
        )

    watchlist_rows = []
    for ticker, sig in sorted(signals_by_ticker.items()):
        if ticker not in holding_tickers:
            decision = quant_by_ticker.get(ticker, {"action": "HOLD", "order_shares": 0, "order_type": "none"})
            watchlist_rows.append(
                {
                    "ticker": ticker,
                    "signals": sig.get("signals", []),
                    "score": sig.get("score", {}),
                    "report_action": decision.get("action", "HOLD"),
                    "order_shares": decision.get("order_shares", 0),
                    "vetoes": decision.get("vetoes", []),
                }
            )

    account = portfolio.get("account", {})
    margin_ratio = account.get("margin_ratio")
    return {
        "account": {
            "total_assets": account.get("total_assets"),
            "available_cash": account.get("available_cash"),
            "margin_ratio": margin_ratio,
            "margin_ratio_label": "委託保証金率",
            "margin_ratio_text": f"{float(margin_ratio):.2f}%" if margin_ratio is not None else "-",
        },
        "macro_context": signals.get("macro_context", {}),
        "portfolio_analytics": analytics,
        "holdings": holding_rows,
        "watchlist": watchlist_rows,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Build report_context.json for stock-advisor reports")
    parser.add_argument("--portfolio", required=True)
    parser.add_argument("--signals", required=True)
    parser.add_argument("--backtest-dir", required=True)
    parser.add_argument("--portfolio-analytics", required=True)
    parser.add_argument("--quant-decisions", required=True)
    parser.add_argument("-o", "--output", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    with open(args.portfolio) as f:
        portfolio = yaml.safe_load(f)
    context = build_context(
        portfolio=portfolio,
        signals=load_json(args.signals),
        backtest_dir=args.backtest_dir,
        analytics=load_json(args.portfolio_analytics),
        quant=load_json(args.quant_decisions),
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(context, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run context tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_report_context_builder.py -q
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit deterministic context builder**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py
git -C /Users/fujie/.dotfiles commit -m "feat: add stock report context builder"
```

Expected: commit succeeds with builder and tests.

## Task 3: Add Position-Level Quant Decisions

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`

- [ ] **Step 1: Add schema tests**

Append to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py`:

```python
from quant_schema import PositionDecision


def test_position_decision_requires_lot_sized_order():
    decision = PositionDecision(
        position_id="5803.T:信用:2",
        ticker="5803.T",
        position_type="信用",
        action="REDUCE",
        quantity=100,
        order_shares=100,
        reason="negative_walk_forward",
    )
    assert decision.order_shares == 100


def test_position_decision_rejects_non_lot_order():
    with pytest.raises(ValueError):
        PositionDecision(
            position_id="5803.T:信用:2",
            ticker="5803.T",
            position_type="信用",
            action="REDUCE",
            quantity=100,
            order_shares=50,
            reason="negative_walk_forward",
        )
```

- [ ] **Step 2: Add `PositionDecision` dataclass**

Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py`:

```python
@dataclass
class PositionDecision:
    position_id: str
    ticker: str
    position_type: str
    action: str
    quantity: int
    order_shares: int = 0
    reason: str = ""
    expiry_date: str | None = None
    unrealized_pnl_pct: float | None = None

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {self.action!r}")
        if self.quantity < 0:
            raise ValueError("quantity must be >= 0")
        if self.order_shares < 0:
            raise ValueError("order_shares must be >= 0")
        if self.order_shares % 100 != 0:
            raise ValueError("order_shares must be a 100-share lot")
        if self.order_shares > self.quantity:
            raise ValueError("order_shares must not exceed quantity")
```

Add a field to `QuantDecision`:

```python
    position_decisions: list[PositionDecision] = field(default_factory=list)
```

- [ ] **Step 3: Add engine tests for mixed positions**

Append to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`:

```python
def test_reduce_prefers_margin_lot_when_ticker_has_mixed_positions():
    signal = {"action": "REDUCE", "current_price": 4820, "atr": 150, "reduce_shares": 100}
    bt = {
        "total_trades": 18,
        "wins": 8,
        "losses": 10,
        "avg_win_pct": 2.0,
        "avg_loss_pct": -2.5,
        "walk_forward": {"verdict": "insufficient_data", "overfit_detected": True},
    }
    pf = make_portfolio(
        holdings=[
            {"ticker": "5803.T", "quantity": 200, "current_price": 4820, "cost_price": 4200, "position_type": "現物"},
            {"ticker": "5803.T", "quantity": 100, "current_price": 4820, "cost_price": 5200, "position_type": "信用", "expiry_date": "2026-07-15"},
        ]
    )
    decision = make_decision("5803.T", signal, bt, pf, {})
    assert decision.order_shares == 100
    assert decision.position_decisions[0].position_type == "信用"
    assert decision.position_decisions[0].order_shares == 100


def test_appreciation_driven_position_over_cap_becomes_watch_veto():
    signal = {"action": "HOLD", "current_price": 2000, "atr": 50}
    pf = make_portfolio(
        holdings=[
            {"ticker": "1515.T", "quantity": 1500, "current_price": 2000, "cost_price": 900, "position_type": "現物"}
        ],
        total_assets=10_000_000,
    )
    decision = make_decision("1515.T", signal, None, pf, {})
    assert "position_over_cap_watch" in decision.vetoes
    assert "position_over_cap_reduce" not in decision.vetoes
    assert decision.action == "HOLD"
```

- [ ] **Step 4: Implement position selection**

Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`:

```python
def _held_positions(portfolio, ticker):
    positions = []
    for index, holding in enumerate(portfolio.get("holdings", []), start=1):
        if holding.get("ticker") != ticker:
            continue
        current = float(holding.get("current_price", 0))
        cost = float(holding.get("cost_price", 0))
        pnl_pct = ((current - cost) / cost * 100) if cost > 0 else None
        positions.append(
            {
                **holding,
                "position_id": f'{ticker}:{holding.get("position_type", "現物")}:{index}',
                "unrealized_pnl_pct": pnl_pct,
            }
        )
    return positions


def _rank_reduce_positions(positions):
    return sorted(
        positions,
        key=lambda p: (
            0 if p.get("position_type") == "信用" else 1,
            p.get("expiry_date") or "9999-12-31",
            p.get("unrealized_pnl_pct") if p.get("unrealized_pnl_pct") is not None else 0,
        ),
    )
```

Use these helpers inside `make_decision` to allocate `order_shares` across positions and serialize each `PositionDecision`.

- [ ] **Step 5: Replace blunt position cap veto**

Modify `make_decision` so appreciation-driven concentration becomes a watch note:

```python
if total_assets > 0 and current_value / total_assets > MAX_POSITION_PCT:
    if cost_price > 0 and entry_price > cost_price and action == "HOLD":
        vetoes.append("position_over_cap_watch")
    else:
        vetoes.append("position_over_cap_reduce")
```

Remove the direct call to `position_cap_vetoes(...)` from this path after the new logic is covered.

- [ ] **Step 6: Run quant tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_schema.py tests/test_quant_decision_engine.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit position-level quant decisions**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py
git -C /Users/fujie/.dotfiles commit -m "feat: add position-level quant decisions"
```

Expected: commit succeeds with schema, engine, and tests.

## Task 4: Validate Generated Reports

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`

- [ ] **Step 1: Write validation tests**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`:

```python
import os
import subprocess
import tempfile


SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(SCRIPTS_DIR, ".venv", "bin", "python")
VALIDATOR = os.path.join(SCRIPTS_DIR, "validate_report.py")
FIXTURE_DIR = os.path.join(SCRIPTS_DIR, "tests", "fixtures", "report_quality")


def run_validator(report_text):
    with tempfile.TemporaryDirectory() as tmpdir:
        report = os.path.join(tmpdir, "report.md")
        with open(report, "w") as f:
            f.write(report_text)
        return subprocess.run(
            [
                PYTHON,
                VALIDATOR,
                "--report", report,
                "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
                "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
                "--backtest-dir", os.path.join(FIXTURE_DIR, "backtest"),
            ],
            capture_output=True,
            text=True,
        )


def test_rejects_invented_signal_name():
    result = run_validator("285A.T momentum_rising_80 uptrend_bb volume_breakout")
    assert result.returncode == 1
    assert "invented signal" in result.stderr


def test_rejects_quant_action_override():
    result = run_validator("285A.T アクション: 保有継続")
    assert result.returncode == 1
    assert "quant action mismatch" in result.stderr


def test_rejects_wrong_account_label():
    result = run_validator("信用倍率1,124倍")
    assert result.returncode == 1
    assert "wrong account label" in result.stderr


def test_accepts_artifact_aligned_snippet():
    result = run_validator("285A.T アクション: 一部売却 100株 trend_following momentum overbought WF判定 unstable 委託保証金率")
    assert result.returncode == 0
```

- [ ] **Step 2: Implement validator**

Create `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py`:

```python
#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from pathlib import Path


ACTION_WORDS = {
    "BUY": ["追加買い", "買い"],
    "HOLD": ["保有継続", "見送り"],
    "REDUCE": ["一部売却", "売却"],
    "SELL": ["全株売却", "売却"],
    "NO_TRADE": ["見送り", "取引なし"],
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def allowed_signal_rules(signals):
    rules = set()
    tickers = set()
    for item in signals.get("results", []):
        tickers.add(item.get("ticker", ""))
        for signal in item.get("signals", []):
            rule = signal.get("rule")
            if rule:
                rules.add(rule)
    return tickers, rules


def quant_actions(quant):
    return {item["ticker"]: item for item in quant.get("decisions", [])}


def backtest_verdicts(backtest_dir):
    verdicts = {}
    for path in Path(backtest_dir).glob("*.json"):
        data = load_json(path)
        consensus = data.get("walk_forward", {}).get("consensus", {})
        verdicts[path.stem] = consensus.get("verdict")
    return verdicts


def fail(message):
    print(message, file=sys.stderr)
    return 1


def validate(report, signals, quant, backtest_dir):
    tickers, rules = allowed_signal_rules(signals)
    known_tokens = rules | tickers
    invented = [
        token
        for token in re.findall(r"\b[a-z][a-z0-9_]{3,}\b", report)
        if "_" in token and token not in known_tokens
    ]
    if invented:
        return fail(f"invented signal: {invented[0]}")

    if "信用倍率" in report:
        return fail("wrong account label: use 委託保証金率")

    for ticker, decision in quant_actions(quant).items():
        if ticker not in report:
            continue
        action = decision.get("action", "HOLD")
        accepted = ACTION_WORDS.get(action, [])
        ticker_section = report[report.find(ticker): report.find("\n### ", report.find(ticker) + 1)]
        if action in ("REDUCE", "SELL") and not any(word in ticker_section for word in accepted):
            return fail(f"quant action mismatch: {ticker} must remain {action}")

    verdicts = backtest_verdicts(backtest_dir)
    if "robust" in report:
        for ticker, verdict in verdicts.items():
            if ticker in report and verdict != "robust":
                return fail(f"walk-forward mismatch: {ticker} is {verdict}, not robust")

    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="Validate stock-advisor report against source artifacts")
    parser.add_argument("--report", required=True)
    parser.add_argument("--signals", required=True)
    parser.add_argument("--quant-decisions", required=True)
    parser.add_argument("--backtest-dir", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    with open(args.report) as f:
        report = f.read()
    raise SystemExit(validate(report, load_json(args.signals), load_json(args.quant_decisions), args.backtest_dir))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run validator tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_validate_report.py -q
```

Expected: all 4 tests pass.

- [ ] **Step 4: Commit validator**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/validate_report.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py
git -C /Users/fujie/.dotfiles commit -m "feat: validate stock advisor reports"
```

Expected: commit succeeds.

## Task 5: Wire Context and Validation into the Skill

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/skills/stock-report/SKILL.md`

- [ ] **Step 1: Update main pipeline**

In `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`, after `quant_decisions.json` generation, add:

```markdown
### Step 2e: レポート用コンテキスト生成

以下を実行し、レポート生成には `report_context.json` を唯一の入力コンテキストとして使う:

```bash
~/.Codex/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.Codex/skills/stock-advisor/scripts/report_context_builder.py \
  --portfolio /Users/fujie/code/playground/stock-price-analyze/data/portfolio.yaml \
  --signals results/YYYY-MM-DD/signals.json \
  --backtest-dir results/YYYY-MM-DD/backtest \
  --portfolio-analytics results/YYYY-MM-DD/portfolio_analytics.json \
  --quant-decisions results/YYYY-MM-DD/quant_decisions.json \
  -o results/YYYY-MM-DD/report_context.json
```

レポート提出前に以下を実行する:

```bash
~/.Codex/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.Codex/skills/stock-advisor/scripts/validate_report.py \
  --report results/YYYY-MM-DD/report.md \
  --signals results/YYYY-MM-DD/signals.json \
  --quant-decisions results/YYYY-MM-DD/quant_decisions.json \
  --backtest-dir results/YYYY-MM-DD/backtest
```
```

- [ ] **Step 2: Update stock-report rules**

In `/Users/fujie/.dotfiles/claude/skills/stock-advisor/skills/stock-report/SKILL.md`, add this rule under `## 分析原則`:

```markdown
- **report_context.json を正とする**: レポートのアクション、数量、シグナル名、WF判定、口座ラベル、watchlist区分は `report_context.json` からそのまま転記する。LLMが補正・改名・格上げしない。
- **取引指示の上書き禁止**: `report_action` が `HOLD` または `NO_TRADE` の場合、本文で BUY/SELL/一部売却に格上げしない。`REDUCE` または `SELL` の数量を減らす場合は、`手動確認メモ` に理由を書くが、`本日の優先アクション` は `report_context.json` の数量を維持する。
- **watchlist分離**: `watchlist` は `注目銘柄（エントリ判断）` にのみ出し、保有銘柄別詳細や取引指示一覧に混ぜない。
- **単位の固定**: `margin_ratio_label` は必ず `委託保証金率` とし、`margin_ratio_text` の `%` 表記をそのまま使う。`change_pct` を bp と書かない。
```

- [ ] **Step 3: Commit skill wiring**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md /Users/fujie/.dotfiles/claude/skills/stock-advisor/skills/stock-report/SKILL.md
git -C /Users/fujie/.dotfiles commit -m "docs: require artifact-aligned stock reports"
```

Expected: commit succeeds.

## Task 6: End-to-End Verification

**Files:**
- Verify only; no planned code changes.

- [ ] **Step 1: Run unit tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_schema.py tests/test_quant_decision_engine.py tests/test_report_context_builder.py tests/test_validate_report.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Build context for the 2026-05-30 run**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/python report_context_builder.py \
  --portfolio /Users/fujie/code/playground/stock-price-analyze/data/portfolio.yaml \
  --signals /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/signals.json \
  --backtest-dir /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/backtest \
  --portfolio-analytics /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/portfolio_analytics.json \
  --quant-decisions /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/quant_decisions.json \
  -o /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/report_context.json
```

Expected: `report_context.json` is created and contains holdings separate from watchlist.

- [ ] **Step 3: Confirm current bad report fails validation**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/python validate_report.py \
  --report /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/report.md \
  --signals /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/signals.json \
  --quant-decisions /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/quant_decisions.json \
  --backtest-dir /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/backtest
```

Expected: non-zero exit with one of:

```text
invented signal
quant action mismatch
wrong account label
walk-forward mismatch
```

- [ ] **Step 4: Regenerate report using `report_context.json`**

Run the `stock-report` step with this instruction added to the prompt:

```text
Use /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/report_context.json as the source of truth. Do not override report_action, order_shares, signal rule names, walk_forward.verdict, margin_ratio_label, or margin_ratio_text.
```

Expected: new report contains:

```text
285A.T: 一部売却 100株
5803.T: 一部売却 300株
委託保証金率 1124.46%
WF判定 unstable
WF判定 insufficient_data
```

- [ ] **Step 5: Confirm regenerated report passes validation**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/python validate_report.py \
  --report /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/report.md \
  --signals /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/signals.json \
  --quant-decisions /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/quant_decisions.json \
  --backtest-dir /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/backtest
```

Expected: exit code 0.

- [ ] **Step 6: Review git state**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short
git -C /Users/fujie/code status --short
```

Expected:

```text

```

after all implementation commits are complete, except intentionally untracked generated daily outputs under ignored results directories.

## Self-Review

- Spec coverage: The plan covers quant/action overrides, invented signal names, WF label inflation, account unit errors, mixed position handling, watchlist separation, prompt rules, and verification.
- Security review: No brokerage Cookies, credentials, or private SBI session data are added to fixtures. Fixtures contain synthetic prices and positions only.
- Simplicity review: The plan avoids a full report generator rewrite. It adds a deterministic context boundary and a validator around the existing LLM report flow.
- Git review: Source changes belong in `/Users/fujie/.dotfiles`; generated run outputs remain under `/Users/fujie/code/playground/stock-price-analyze/results` and should not be committed unless intentionally curated as fixtures.
