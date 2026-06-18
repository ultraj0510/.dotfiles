# Stock Advisor Position Risk Model Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve `stock-advisor` so concentrated positions are judged with professional risk context instead of mechanically selling winners or vaguely holding large losers.

**Architecture:** Keep `action` compatible with the current pipeline (`BUY`, `HOLD`, `REDUCE`, `SELL`, `NO_TRADE`) and add deterministic risk posture fields beside it. The quant engine will separate immediate trade actions from advisory risk plans: profit-protection for strong winners like `285A.T`, and rebound-trim / no-averaging-down plans for large volatile losers like `1515.T`.

**Tech Stack:** Python 3.14, pytest, JSON/YAML artifacts, existing `stock-advisor` scripts under `/Users/fujie/.dotfiles/claude/skills/stock-advisor`.

---

## Current Diagnosis

The latest implementation fixed report hallucination: the report now follows `quant_decisions.json`. The remaining problem is that `quant_decision_engine.py` can still generate overly blunt decisions.

Observed from `/Users/fujie/code/playground/stock-price-analyze/results/2026-05-30`:

- `285A.T`
  - Holding: 100 spot shares.
  - Cost price: ¥15,136.
  - Current price: ¥65,850.
  - Unrealized PnL: +335%.
  - Current portfolio weight: 33.5%.
  - Cost-basis portfolio weight: 7.7%.
  - Signals: `trend_following` BUY, `momentum` BUY, `overbought` SELL.
  - Backtest baseline is strong, but walk-forward verdict is `unstable`.
  - Current quant result is `REDUCE 100`, which is effectively a full exit. This is too aggressive because the only sell-side evidence is overbought/concentration, while trend and momentum are still strong.

- `1515.T`
  - Holding: 3,000 spot shares.
  - Cost price: ¥3,552.
  - Current price: ¥2,397.
  - Unrealized PnL: -32.5%.
  - Current portfolio weight: 36.6%.
  - Cost-basis portfolio weight: 54.2%.
  - Signals: none, score `HOLD`, trend state `downtrend`.
  - Walk-forward verdict is `insufficient_data`, overfit detected.
  - Current quant result is `HOLD`, which avoids forced selling, but it does not explain a professional plan for a large volatile loser.

Root causes:

- `_normalize_signal_single()` turns any SELL signal into `REDUCE`, even when BUY signals are also active and `score.recommendation` is `HOLD`.
- Position cap is treated mainly as a sell/reduce pressure, without distinguishing appreciation-driven concentration from loss-driven concentration.
- A 100-share holding can receive `REDUCE 100`, which is not a partial sale. It is full exit and should require stronger evidence.
- The report context does not expose downside impact numbers such as "10% decline equals ¥658,500 portfolio loss".
- The engine does not output a structured rebound-trim plan for large losing positions.

## File Responsibility Map

- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py`
  - Add optional fields to `QuantDecision`: `risk_posture`, `protective_stop_price`, `portfolio_weight_pct`, `cost_basis_weight_pct`, `unrealized_pnl_pct`, `downside_10pct_yen`, `advisory_plan`.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`
  - Preserve signal mix instead of collapsing any SELL signal to `REDUCE`.
  - Add position metrics and risk posture classification.
  - Add single-lot winner guard to avoid full exit from one overbought signal.
  - Add large-loser rebound-trim advisory plan.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`
  - Pass the new quant fields into `report_context.json`.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/skills/stock-report/SKILL.md`
  - Require reports to explain risk posture and advisory plan separately from immediate trade action.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py`
  - Test new schema fields remain backward compatible.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`
  - Add 285A and 1515 regression tests.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`
  - Assert risk fields are exported.
- Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_validate_report.py`
  - Add report validation for "REDUCE 100 on 100-share winner" prevention through quant fixture.

## Task 1: Add Regression Tests for 285A Winner Protection

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`

- [ ] **Step 1: Add failing test for mixed BUY/SELL signals**

Append this test to `TestMakeDecision` in `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`:

```python
    def test_mixed_buy_and_overbought_sell_keeps_single_lot_winner_hold(self):
        signal = {
            "action": "HOLD",
            "current_price": 65850,
            "atr": 4695.38,
            "signals": [
                {"type": "BUY", "rule": "trend_following", "strength": "strong"},
                {"type": "BUY", "rule": "momentum", "strength": "moderate"},
                {"type": "SELL", "rule": "overbought", "strength": "moderate"},
            ],
            "indicators": {
                "close_10_ema": "58362.71",
                "boll": "50724.0",
                "boll_lb": "32223.25",
                "boll_ub": "69224.75",
                "rsi": "74.75",
                "52w_position": "100.0",
            },
        }
        bt = {
            "total_trades": 9,
            "wins": 7,
            "losses": 2,
            "avg_win_pct": 50.07,
            "avg_loss_pct": -10.37,
            "walk_forward": {"verdict": "unstable", "overfit_detected": False},
        }
        pf = make_portfolio(
            holdings=[
                {
                    "ticker": "285A.T",
                    "quantity": 100,
                    "current_price": 65850,
                    "cost_price": 15136,
                    "position_type": "現物",
                }
            ],
            total_assets=19661379,
            available_cash=624634,
        )
        decision = make_decision("285A.T", signal, bt, pf, {})
        assert decision.action == "HOLD"
        assert decision.order_shares == 0
        assert decision.risk_posture == "protect_profit"
        assert "single_lot_full_exit_guard" in decision.vetoes
        assert "position_over_cap_watch" in decision.vetoes
        assert decision.protective_stop_price == 58362.71
        assert decision.downside_10pct_yen == 658500
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_decision_engine.py::TestMakeDecision::test_mixed_buy_and_overbought_sell_keeps_single_lot_winner_hold -q
```

Expected: FAIL because `QuantDecision` does not have `risk_posture`, `protective_stop_price`, or `downside_10pct_yen`, and the current engine may still produce `REDUCE`.

## Task 2: Add Regression Tests for 1515 Large-Loser Rebalance Plan

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`

- [ ] **Step 1: Add failing test for large loss concentration**

Append this test to `TestMakeDecision`:

```python
    def test_large_loss_concentration_gets_rebound_trim_plan_without_buyback(self):
        signal = {
            "action": "HOLD",
            "current_price": 2397,
            "atr": 173.98,
            "trend_state": "downtrend",
            "signals": [],
            "indicators": {
                "close_10_ema": "2408.45",
                "close_50_sma": "2561.17",
                "boll": "2440.4",
                "boll_lb": "2162.25",
                "boll_ub": "2718.55",
                "10d_return": "-8.09",
                "20d_return": "-1.03",
            },
        }
        bt = {
            "total_trades": 29,
            "wins": 10,
            "losses": 19,
            "avg_win_pct": 15.0,
            "avg_loss_pct": -4.71,
            "walk_forward": {"verdict": "insufficient_data", "overfit_detected": True},
        }
        pf = make_portfolio(
            holdings=[
                {
                    "ticker": "1515.T",
                    "quantity": 3000,
                    "current_price": 2397,
                    "cost_price": 3552,
                    "position_type": "現物",
                }
            ],
            total_assets=19661379,
            available_cash=624634,
        )
        decision = make_decision("1515.T", signal, bt, pf, {})
        assert decision.action == "HOLD"
        assert decision.order_shares == 0
        assert decision.risk_posture == "rebalance_on_strength"
        assert "position_over_cap_loss_concentration" in decision.vetoes
        assert decision.portfolio_weight_pct == 36.57
        assert decision.cost_basis_weight_pct == 54.20
        assert decision.unrealized_pnl_pct == -32.52
        assert decision.advisory_plan == {
            "mode": "trim_on_rebound",
            "trim_shares": 300,
            "trim_trigger_price": 2440.4,
            "buyback_allowed": False,
            "buyback_block_reason": "downtrend_and_position_over_30pct",
        }
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_decision_engine.py::TestMakeDecision::test_large_loss_concentration_gets_rebound_trim_plan_without_buyback -q
```

Expected: FAIL because the advisory fields are not implemented.

## Task 3: Extend QuantDecision Schema Backward-Compatibly

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py`

- [ ] **Step 1: Add schema test**

Append to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py`:

```python
def test_quant_decision_allows_risk_posture_metadata():
    decision = QuantDecision(
        ticker="285A.T",
        action="HOLD",
        risk_posture="protect_profit",
        protective_stop_price=58362.71,
        portfolio_weight_pct=33.49,
        cost_basis_weight_pct=7.70,
        unrealized_pnl_pct=335.06,
        downside_10pct_yen=658500,
        advisory_plan={"mode": "trail_stop", "stop_source": "close_10_ema"},
    )
    assert decision.action == "HOLD"
    assert decision.risk_posture == "protect_profit"
    assert decision.advisory_plan["mode"] == "trail_stop"
```

- [ ] **Step 2: Modify schema**

Add these fields to `QuantDecision` in `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py` after `limit_price`:

```python
    risk_posture: str = "neutral"
    protective_stop_price: float | None = None
    portfolio_weight_pct: float | None = None
    cost_basis_weight_pct: float | None = None
    unrealized_pnl_pct: float | None = None
    downside_10pct_yen: int | None = None
    advisory_plan: dict = field(default_factory=dict)
```

Do not add these fields to `ACTIONS`; they are metadata, not trade actions.

- [ ] **Step 3: Run schema tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_schema.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit schema change**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py
git -C /Users/fujie/.dotfiles commit -m "feat: add quant risk posture metadata"
```

Expected: commit succeeds. If `/Users/fujie/.dotfiles` still has the existing ahead commit `fix: include WF verdict names in validator known tokens`, keep it and create a new commit on top.

## Task 4: Preserve Signal Mix Instead of Auto-Reducing on Any SELL

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`

- [ ] **Step 1: Modify `_normalize_signal_single()`**

Replace the body after `flat = ...` in `_normalize_signal_single()` with:

```python
    raw_signals = raw.get("signals", [])
    buy_signals = [s for s in raw_signals if s.get("type") == "BUY"]
    sell_signals = [s for s in raw_signals if s.get("type") == "SELL"]
    strong_sell_rules = {
        s.get("rule")
        for s in sell_signals
        if s.get("strength") == "strong" or s.get("rule") in {"drawdown_stop", "momentum_breakdown"}
    }

    flat["signals"] = raw_signals
    flat["indicators"] = indicators
    flat["trend_state"] = raw.get("trend_state", "")
    flat["buy_signal_count"] = len(buy_signals)
    flat["sell_signal_count"] = len(sell_signals)
    flat["strong_sell_rules"] = sorted(strong_sell_rules)

    if rec == "HOLD_SELL" or strong_sell_rules:
        flat["action"] = "REDUCE"

    return flat
```

Remove the old block:

```python
    sell_signals = [s for s in raw.get("signals", []) if s.get("type") == "SELL"]
    if sell_signals and action in ("HOLD", "BUY"):
        flat["action"] = "REDUCE"
```

- [ ] **Step 2: Run 285A failing test**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_decision_engine.py::TestMakeDecision::test_mixed_buy_and_overbought_sell_keeps_single_lot_winner_hold -q
```

Expected: it may still fail because risk posture fields are not yet populated, but the action should now be closer to `HOLD`.

## Task 5: Add Position Metrics and Risk Posture Classification

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`

- [ ] **Step 1: Add helper functions**

Add these helpers after `_allocate_reduce_to_positions()`:

```python
def _position_metrics(total_assets: float, positions: list[dict]) -> dict:
    current_value = sum(float(p.get("quantity", 0)) * float(p.get("current_price", 0)) for p in positions)
    cost_basis = sum(float(p.get("quantity", 0)) * float(p.get("cost_price", 0)) for p in positions)
    unrealized_pnl_pct = ((current_value - cost_basis) / cost_basis * 100) if cost_basis > 0 else None
    return {
        "current_value": current_value,
        "cost_basis": cost_basis,
        "portfolio_weight_pct": round(current_value / total_assets * 100, 2) if total_assets > 0 else None,
        "cost_basis_weight_pct": round(cost_basis / total_assets * 100, 2) if total_assets > 0 else None,
        "unrealized_pnl_pct": round(unrealized_pnl_pct, 2) if unrealized_pnl_pct is not None else None,
        "downside_10pct_yen": int(round(current_value * 0.10)),
    }


def _indicator_float(signal_info: dict, key: str) -> float | None:
    value = signal_info.get("indicators", {}).get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _protective_stop_price(signal_info: dict, entry_price: float, atr: float) -> float | None:
    ema10 = _indicator_float(signal_info, "close_10_ema")
    if ema10 and ema10 > 0:
        return round(ema10, 2)
    if entry_price > 0 and atr > 0:
        return round(entry_price - atr * 2, 2)
    return None


def _rebound_trim_plan(signal_info: dict, current_qty: int, portfolio_weight_pct: float | None) -> dict:
    boll_mid = _indicator_float(signal_info, "boll")
    ema10 = _indicator_float(signal_info, "close_10_ema")
    trigger = max(v for v in [boll_mid, ema10] if v is not None)
    trim_shares = min(600, max(300, (current_qty // 10 // 100) * 100))
    if portfolio_weight_pct is not None and portfolio_weight_pct < 30:
        trim_shares = min(trim_shares, 300)
    return {
        "mode": "trim_on_rebound",
        "trim_shares": trim_shares,
        "trim_trigger_price": round(trigger, 2),
        "buyback_allowed": False,
        "buyback_block_reason": "downtrend_and_position_over_30pct",
    }
```

- [ ] **Step 2: Replace position cap logic**

In `make_decision()`, after `entry_price` and `atr` are set, add:

```python
    positions = _held_positions(portfolio, ticker)
    metrics = _position_metrics(total_assets, positions)
```

Replace the current position cap block:

```python
    if total_assets > 0 and current_value / total_assets > MAX_POSITION_PCT:
        if cost_price > 0 and entry_price > cost_price and signal_action == "HOLD":
            vetoes.append("position_over_cap_watch")
        elif "position_over_cap" not in vetoes:
            vetoes.append("position_over_cap_reduce")
```

with:

```python
    risk_posture = "neutral"
    protective_stop = None
    advisory_plan = {}
    portfolio_weight_pct = metrics["portfolio_weight_pct"]
    unrealized_pnl_pct = metrics["unrealized_pnl_pct"]

    if portfolio_weight_pct is not None and portfolio_weight_pct > MAX_POSITION_PCT * 100:
        if unrealized_pnl_pct is not None and unrealized_pnl_pct >= 50:
            risk_posture = "protect_profit"
            protective_stop = _protective_stop_price(signal_info, entry_price, atr)
            advisory_plan = {
                "mode": "trail_stop",
                "stop_source": "close_10_ema_or_2atr",
                "sell_only_if_stop_breaks": True,
            }
            vetoes.append("position_over_cap_watch")
        elif unrealized_pnl_pct is not None and unrealized_pnl_pct < 0:
            risk_posture = "rebalance_on_strength"
            advisory_plan = _rebound_trim_plan(signal_info, current_qty, portfolio_weight_pct)
            vetoes.append("position_over_cap_loss_concentration")
        else:
            vetoes.append("position_over_cap_watch")
```

- [ ] **Step 3: Add single-lot full-exit guard**

Before the `elif action in ("SELL", "REDUCE"):` block allocates shares, add:

```python
    if (
        action == "REDUCE"
        and current_qty == 100
        and risk_posture == "protect_profit"
        and not signal_info.get("strong_sell_rules")
    ):
        action = "HOLD"
        vetoes.append("single_lot_full_exit_guard")
        explanations.append("single-lot winner protected; use trailing stop instead of full exit")
```

- [ ] **Step 4: Return new fields**

Add these arguments to the `QuantDecision(...)` return:

```python
        risk_posture=risk_posture,
        protective_stop_price=protective_stop,
        portfolio_weight_pct=metrics["portfolio_weight_pct"],
        cost_basis_weight_pct=metrics["cost_basis_weight_pct"],
        unrealized_pnl_pct=metrics["unrealized_pnl_pct"],
        downside_10pct_yen=metrics["downside_10pct_yen"],
        advisory_plan=advisory_plan,
```

- [ ] **Step 5: Run targeted quant tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest \
  tests/test_quant_decision_engine.py::TestMakeDecision::test_mixed_buy_and_overbought_sell_keeps_single_lot_winner_hold \
  tests/test_quant_decision_engine.py::TestMakeDecision::test_large_loss_concentration_gets_rebound_trim_plan_without_buyback \
  -q
```

Expected: both tests pass.

- [ ] **Step 6: Run full quant decision tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_decision_engine.py tests/test_quant_schema.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit quant model change**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py
git -C /Users/fujie/.dotfiles commit -m "feat: refine concentrated position risk decisions"
```

Expected: commit succeeds.

## Task 6: Serialize New Fields to `quant_decisions.json`

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`

- [ ] **Step 1: Extend CLI serialization**

In `main()`, inside the decision dict written to `output["decisions"]`, add:

```python
                "risk_posture": d.risk_posture,
                "protective_stop_price": d.protective_stop_price,
                "portfolio_weight_pct": d.portfolio_weight_pct,
                "cost_basis_weight_pct": d.cost_basis_weight_pct,
                "unrealized_pnl_pct": d.unrealized_pnl_pct,
                "downside_10pct_yen": d.downside_10pct_yen,
                "advisory_plan": d.advisory_plan,
```

- [ ] **Step 2: Add CLI smoke assertions**

In `TestCLIFixture.test_fixture_cli_smoke`, after `d = data["decisions"][0]`, add:

```python
        assert "risk_posture" in d
        assert "portfolio_weight_pct" in d
        assert "advisory_plan" in d
```

- [ ] **Step 3: Run CLI smoke test**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_quant_decision_engine.py::TestCLIFixture::test_fixture_cli_smoke -q
```

Expected: PASS.

- [ ] **Step 4: Commit serialization**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py
git -C /Users/fujie/.dotfiles commit -m "feat: serialize quant risk posture"
```

Expected: commit succeeds.

## Task 7: Expose Risk Fields in Report Context

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`

- [ ] **Step 1: Add context test**

Append to `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py`:

```python
def test_quant_risk_posture_fields_are_exported():
    context = build_context()
    decisions = context["quant_decisions"]["decisions"]
    sample = decisions["285A.T"]
    for key in [
        "risk_posture",
        "protective_stop_price",
        "portfolio_weight_pct",
        "cost_basis_weight_pct",
        "unrealized_pnl_pct",
        "downside_10pct_yen",
        "advisory_plan",
    ]:
        assert key in sample
```

- [ ] **Step 2: Update report context builder**

In `build_quant_decisions()` in `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py`, add these fields to each ticker decision:

```python
            "risk_posture": d.get("risk_posture", "neutral"),
            "protective_stop_price": d.get("protective_stop_price"),
            "portfolio_weight_pct": d.get("portfolio_weight_pct"),
            "cost_basis_weight_pct": d.get("cost_basis_weight_pct"),
            "unrealized_pnl_pct": d.get("unrealized_pnl_pct"),
            "downside_10pct_yen": d.get("downside_10pct_yen"),
            "advisory_plan": d.get("advisory_plan", {}),
```

- [ ] **Step 3: Update report-quality fixture**

Modify `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/quant_decisions.json` and add these fields to the `285A.T` object:

```json
      "risk_posture": "protect_profit",
      "protective_stop_price": 58362.71,
      "portfolio_weight_pct": 33.49,
      "cost_basis_weight_pct": 7.7,
      "unrealized_pnl_pct": 335.06,
      "downside_10pct_yen": 658500,
      "advisory_plan": {"mode": "trail_stop", "sell_only_if_stop_breaks": true}
```

- [ ] **Step 4: Run context tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest tests/test_report_context_builder.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit context export**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/report_context_builder.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_report_context_builder.py /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/fixtures/report_quality/quant_decisions.json
git -C /Users/fujie/.dotfiles commit -m "feat: expose risk posture in report context"
```

Expected: commit succeeds.

## Task 8: Update Report Rules for Professional Portfolio Advice

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/skills/stock-report/SKILL.md`

- [ ] **Step 1: Add reporting rules**

Add this section under `## 分析原則`:

```markdown
## 集中ポジションの説明ルール

- `action` と `risk_posture` を分けて説明する。`action=HOLD` かつ `risk_posture=protect_profit` は「売却」ではなく「利益を伸ばしながら防衛」と書く。
- `quantity=100` の現物で `risk_posture=protect_profit` の場合、`REDUCE 100` を「一部売却」と書かない。100株売却は全退出であり、`strong_sell_rules` または `drawdown_stop` がない限り推奨しない。
- 取得コストが低い銘柄は、元本リスクと現在価値リスクを分ける。`cost_basis_weight_pct` と `portfolio_weight_pct` を両方表示する。
- 大きな含み益銘柄は `downside_10pct_yen` を明示し、「売らない場合に何円の評価益が揺れるか」を説明する。
- `risk_posture=rebalance_on_strength` は本日売却ではない。戻り局面の縮小計画として `advisory_plan.trim_trigger_price` と `advisory_plan.trim_shares` を表示する。
- `advisory_plan.buyback_allowed=false` の場合、安値買い戻しを推奨しない。まずポジション比率の縮小とトレンド反転確認を優先する。
```

- [ ] **Step 2: Commit report rule update**

Run:

```bash
git -C /Users/fujie/.dotfiles add /Users/fujie/.dotfiles/claude/skills/stock-advisor/skills/stock-report/SKILL.md
git -C /Users/fujie/.dotfiles commit -m "docs: clarify concentrated position report rules"
```

Expected: commit succeeds.

## Task 9: End-to-End Verification on 2026-05-30 Artifacts

**Files:**
- Verify only; no planned source changes.

- [ ] **Step 1: Run all relevant tests**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/pytest \
  tests/test_quant_schema.py \
  tests/test_quant_decision_engine.py \
  tests/test_report_context_builder.py \
  tests/test_validate_report.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 2: Regenerate quant decisions for 2026-05-30 into a temp file**

Run:

```bash
tmpdir="$(mktemp -d)"
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/python quant_decision_engine.py \
  --portfolio /Users/fujie/code/playground/stock-price-analyze/portfolio.yaml \
  --signals /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/signals.json \
  --backtest-dir /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/backtest \
  --portfolio-analytics /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/portfolio_analytics.json \
  -o "$tmpdir/quant_decisions.json"
python3 - <<PY
import json, os
path = os.path.join("$tmpdir", "quant_decisions.json")
data = json.load(open(path))
for ticker in ["285A.T", "1515.T"]:
    d = next(item for item in data["decisions"] if item["ticker"] == ticker)
    print(ticker, d["action"], d["order_shares"], d["risk_posture"], d["vetoes"], d["advisory_plan"])
PY
```

Expected:

```text
285A.T HOLD 0 protect_profit [...]
1515.T HOLD 0 rebalance_on_strength [...]
```

- [ ] **Step 3: Regenerate report context using the temp quant decisions**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/python report_context_builder.py \
  --portfolio /Users/fujie/code/playground/stock-price-analyze/portfolio.yaml \
  --signals /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/signals.json \
  --backtest-dir /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/backtest \
  --portfolio-analytics /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/portfolio_analytics.json \
  --quant-decisions "$tmpdir/quant_decisions.json" \
  -o "$tmpdir/report_context.json"
python3 - <<PY
import json, os
ctx = json.load(open(os.path.join("$tmpdir", "report_context.json")))
for ticker in ["285A.T", "1515.T"]:
    d = ctx["quant_decisions"]["decisions"][ticker]
    print(ticker, d["report_action"], d["risk_posture"], d["portfolio_weight_pct"], d["cost_basis_weight_pct"], d["advisory_plan"])
PY
```

Expected:

```text
285A.T HOLD protect_profit 33.49 7.7 {...}
1515.T HOLD rebalance_on_strength 36.57 54.2 {...}
```

- [ ] **Step 4: Verify existing report validator still passes on current report**

Run:

```bash
cd /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/python validate_report.py \
  --report /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/report.md \
  --signals /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/signals.json \
  --quant-decisions /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/quant_decisions.json \
  --backtest-dir /Users/fujie/code/playground/stock-price-analyze/results/2026-05-30/backtest
```

Expected: exit code 0. This confirms the validator itself is not broken by the schema extension.

- [ ] **Step 5: Review git state**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short --branch
```

Expected: clean working tree after commits, with branch possibly ahead of `origin/main` if commits have not been pushed.

## Professional Decision Policy After This Change

- `285A.T`: no immediate sale from one overbought signal. Keep `action=HOLD`, `risk_posture=protect_profit`, and show a protective stop around the 10-day EMA or 2ATR stop. This respects the user's thesis that upside may continue, while still quantifying current-value downside.
- `1515.T`: no immediate forced liquidation, but no automatic buyback either. Keep `action=HOLD`, `risk_posture=rebalance_on_strength`, and show a rebound trim plan. This respects the user's idea of using volatility, while preventing averaging down into a 36% portfolio-weight loser.

## Self-Review

- Spec coverage: The plan addresses 285A, 1515, cost basis, current-value risk, single-lot full exit, position concentration, volatility-based rebalance planning, report context, and report wording.
- Simplicity review: The plan avoids inventing new trade actions that could break downstream validators. It adds metadata beside existing actions.
- Professional-risk review: The plan does not blindly accept user preference. It keeps 285A invested with protection and treats 1515's buy-low idea as conditional rather than immediately executable.
- Security review: No brokerage Cookie, credential, or private session value is added. Tests use synthetic in-code fixtures or existing local artifacts.
- Git review: `/Users/fujie/.dotfiles` is currently ahead of origin by one commit. Implementation should preserve that commit and add new commits on top.
