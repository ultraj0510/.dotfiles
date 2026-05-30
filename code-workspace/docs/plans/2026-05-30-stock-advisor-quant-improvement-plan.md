# Stock Advisor Quant Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `stock-advisor` をクオンツ取引観点で改善し、シグナル・バックテスト・ファクター・ポートフォリオ制約を一貫した取引判断に統合する。

**Architecture:** 既存の deterministic pipeline (`signal_engine.py`, `backtest_engine.py`, `factor_engine.py`, `portfolio_analytics.py`, `trade_advisor.py`) は活かし、最終段に `quant_decision_engine.py` を追加する。新しい意思決定層は、期待値、取引コスト、執行遅延、サンプル信頼度、相関、ポジション上限、信用期限をまとめて評価し、LLMレポートの前に検証可能な `quant_decisions.json` を生成する。

**Tech Stack:** Python 3.14, pandas, numpy, yfinance, pytest, YAML, JSON, Claude Code skills

---

## Current Baseline

Fresh verification on 2026-05-30:

```bash
python3 -m py_compile \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/signal_engine.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/backtest_engine.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/trade_advisor.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/factor_engine.py \
  /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/portfolio_analytics.py
```

Result: exit code 0.

```bash
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests
```

Result: `68 passed, 16 warnings in 7.98s`.

Plain system `pytest` fails because system Python lacks `numpy`, `pandas`, and `yfinance`. The implementation plan standardizes all stock-advisor verification through the skill venv.

## 現状評価

### すでに良い点

- `signal_engine.py` は LLM 判断に頼らず、RSI、Bollinger、SMA、MACD、ATR、52週位置、出来高比率などから deterministic signal を出す。
- `backtest_engine.py` は transaction cost、slippage、market impact、vol targeting、margin cost、walk-forward、VaR/CVaR、Sharpe CI を持っている。
- `factor_engine.py` は value, momentum, quality, volatility の4ファクターを計算できる。
- `portfolio_analytics.py` は correlation matrix と stress test を持っている。
- `trade_advisor.py` は保有ポジション単位のP/L、過去勝率、factor arbitration、inverse-vol sizing を持っている。

### クオンツ取引観点の主な問題

1. **最終判断が分散している**
   - `signals.json`, `backtest/*.json`, `portfolio_analytics.json`, `trade_advisor.py` の結果が、単一の機械判定 artifact にまとまっていない。
   - LLMレポート側で統合しているため、同じ入力でも最終取引判断の再現性が弱い。

2. **期待値で意思決定していない**
   - 現在は signal score、historical win rate、P/L、trend alignment の足し算が中心。
   - `expected_value_after_cost = p_win * avg_win - (1 - p_win) * avg_loss - transaction_cost` の形で、取引する価値があるかを明示していない。

3. **サンプル数と過学習の扱いが弱い**
   - low sample caveat はあるが、勝率そのものに Bayesian shrinkage が入っていない。
   - IC / Sharpe / walk-forward 結果が「取引禁止のveto」として十分に使われていない。

4. **執行現実性がデフォルトになっていない**
   - `backtest_engine.py` には `execution_delay` があるが、stock-advisorの手順では常用されていない。
   - SELL/PARTIAL_SELLは指値ルールなのに、limit fill probability と未約定時の扱いが意思決定に入っていない。

5. **ポートフォリオ制約が最終注文数量に反映されきっていない**
   - skill本文は「最大ポジション20%」「1トレードリスク2%」を掲げるが、現在のコードの一部は25% capや100-200株の簡易 sizing を使う。
   - 相関、信用期限、現金余力、既存保有比率を使った注文数量の最終調整が一箇所にない。

6. **ファクターが横断比較になっていない**
   - `factor_engine.py` は固定reference medianを使うため、その日の保有 universe 内での相対優位が見えにくい。
   - 日本株小型・ETF・金融・製造などの混在ポートフォリオでは、固定中央値だけだと歪みやすい。

7. **検証コマンドが迷いやすい**
   - system Python でテストすると依存関係不足で失敗する。
   - `setup_env` と skill venv を使う検証手順を `SKILL.md` と README に寄せる必要がある。

## 自己ダメ出し

- 指標を増やすだけでは改善にならない。既存シグナルの説明性と検証可能性を維持し、最終判断の一貫性を上げる。
- 自動売買に近づけすぎない。出力は「注文候補」であり、証券会社への自動発注はこの計画の範囲外にする。
- 最初から高度な最適化を入れない。ブラックボックス化を避け、まず期待値、veto、リスク制約、注文数量の透明なルールを作る。
- 過去データ最適化に寄せすぎない。walk-forwardとshrunk probabilityを通らないシグナルは、勝率が高く見えても取引禁止にできる設計にする。

---

## Recommended Design

### New Output Contract

Create one deterministic artifact before report generation:

```text
/Users/fujie/code/playground/stock-price-analyze/results/<YYYY-MM-DD>/quant_decisions.json
```

Each ticker gets:

```json
{
  "ticker": "7203.T",
  "action": "BUY|HOLD|REDUCE|SELL|NO_TRADE",
  "confidence": "low|moderate|high",
  "expected_value_after_cost_pct": 1.25,
  "p_win_shrunk": 0.56,
  "avg_win_pct": 4.8,
  "avg_loss_pct": -2.9,
  "max_position_value": 3932275,
  "target_shares": 200,
  "order_shares": 100,
  "order_type": "market|limit|none",
  "limit_price": 1234,
  "vetoes": ["low_sample", "negative_walk_forward", "portfolio_concentration"],
  "explanations": ["EV positive after costs", "position cap respected"]
}
```

The LLM report must quote `quant_decisions.json` instead of recomputing final actions from prose.

---

### Task 1: Baseline And Verification Standardization

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`
- Modify: `/Users/fujie/.dotfiles/README.md`

- [ ] **Step 1: Record current baseline**

Run:

```bash
git -C /Users/fujie/.dotfiles status --short
/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q /Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests
```

Expected:

```text
68 passed
```

- [ ] **Step 2: Update verification docs to use the skill venv**

Replace any stock-advisor test instruction that uses plain `pytest` with:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q ~/.claude/skills/stock-advisor/scripts/tests
```

- [ ] **Step 3: Add a warning about system Python**

Add this note to `SKILL.md` under Step 0:

```markdown
stock-advisor tests must run through `scripts/.venv/bin/python`; system Python may not have `numpy`, `pandas`, or `yfinance`.
```

---

### Task 2: Add Deterministic Quant Decision Schema

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_schema.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_schema.py`

- [ ] **Step 1: Add schema module**

Create `quant_schema.py` with dataclasses for:

```python
@dataclass
class QuantDecision:
    ticker: str
    action: str
    confidence: str
    expected_value_after_cost_pct: float | None
    p_win_shrunk: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    max_position_value: float
    target_shares: int
    order_shares: int
    order_type: str
    limit_price: float | None
    vetoes: list[str]
    explanations: list[str]
```

Allowed values:

```python
ACTIONS = {"BUY", "HOLD", "REDUCE", "SELL", "NO_TRADE"}
CONFIDENCE = {"low", "moderate", "high"}
ORDER_TYPES = {"market", "limit", "none"}
```

- [ ] **Step 2: Add validation tests**

Test cases:

- valid BUY with market order passes
- SELL without limit price fails
- NO_TRADE with non-zero order shares fails
- unknown action fails
- negative target shares fails

- [ ] **Step 3: Run schema tests**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q ~/.claude/skills/stock-advisor/scripts/tests/test_quant_schema.py
```

Expected:

```text
5 passed
```

---

### Task 3: Add Signal Reliability And Expected Value Layer

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/signal_reliability.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_signal_reliability.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/trade_advisor.py`

- [ ] **Step 1: Add Bayesian shrinkage**

Create functions:

```python
def shrink_win_probability(wins: int, losses: int, prior_p: float = 0.5, prior_n: int = 10) -> float:
    return (wins + prior_p * prior_n) / (wins + losses + prior_n)
```

Rules:

- `wins + losses == 0` returns `0.5`
- low sample is not discarded, but pulled toward 50%
- prior_n defaults to 10 to keep small samples conservative

- [ ] **Step 2: Add expected value calculation**

Create:

```python
def expected_value_after_cost_pct(
    p_win: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    round_trip_cost_pct: float,
) -> float:
    return p_win * avg_win_pct + (1 - p_win) * avg_loss_pct - round_trip_cost_pct
```

Rules:

- `avg_loss_pct` is negative.
- return is rounded to 4 decimals by the caller.
- EV must be after cost.

- [ ] **Step 3: Add veto classification**

Create:

```python
def reliability_vetoes(sample_count: int, p_win_shrunk: float, ev_after_cost_pct: float, walk_forward: dict | None) -> list[str]:
```

Vetoes:

- `low_sample` when `sample_count < 5`
- `negative_ev` when `ev_after_cost_pct <= 0`
- `negative_walk_forward` when test Sharpe is below 0
- `overfit_walk_forward` when Sharpe train/test difference exceeds 50%

- [ ] **Step 4: Add tests**

Test cases:

- 4 wins / 0 losses shrinks below 100%
- 0 wins / 4 losses shrinks above 0%
- positive raw win rate still gets `negative_ev` when costs dominate
- negative walk-forward adds `negative_walk_forward`
- overfit walk-forward adds `overfit_walk_forward`

- [ ] **Step 5: Run reliability tests**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q ~/.claude/skills/stock-advisor/scripts/tests/test_signal_reliability.py
```

Expected:

```text
5 passed
```

---

### Task 4: Make Backtest Execution More Realistic By Default

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/backtest_engine.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_backtest_engine.py`

- [ ] **Step 1: Use execution delay in stock-advisor workflow**

Update SKILL Step 2b command from:

```bash
backtest_engine.py --ticker "$t" --strategy default --end "$LATEST_TRADING_DAY"
```

to:

```bash
backtest_engine.py --ticker "$t" --strategy default --execution-delay --end "$LATEST_TRADING_DAY"
```

- [ ] **Step 2: Add explicit result metadata**

Ensure each backtest JSON includes:

```json
{
  "execution_model": {
    "execution_delay_days": 1,
    "price_basis": "close",
    "cost_model": "commission_slippage_market_impact"
  }
}
```

- [ ] **Step 3: Add regression test**

Test that `--execution-delay` changes a simple synthetic signal from same-day execution to next-day execution and that metadata is present.

- [ ] **Step 4: Run backtest tests**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q ~/.claude/skills/stock-advisor/scripts/tests/test_backtest_engine.py
```

Expected:

```text
all tests passed
```

---

### Task 5: Add Portfolio-Level Optimizer For Order Sizing

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/portfolio_optimizer.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_portfolio_optimizer.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/trade_advisor.py`

- [ ] **Step 1: Implement hard constraints**

Use these constraints:

- max position value: 20% of total assets
- max one-trade loss: 2% of total assets
- lot size: 100 shares
- BUY cannot exceed available cash
- SELL/PARTIAL_SELL cannot exceed current shares
- margin expiry under 30 days adds `margin_expiry_urgent`
- margin expiry under 60 days adds `margin_expiry_watch`

- [ ] **Step 2: Implement sizing formula**

For BUY:

```text
risk_budget = total_assets * 0.02
per_share_risk = max(entry_price - stop_loss, atr * 2, entry_price * 0.03)
risk_based_shares = floor_to_100(risk_budget / per_share_risk)
cap_based_shares = floor_to_100((total_assets * 0.20 - current_position_value) / entry_price)
cash_based_shares = floor_to_100(available_cash / entry_price)
target_order_shares = min(risk_based_shares, cap_based_shares, cash_based_shares)
```

For SELL/REDUCE:

```text
target_order_shares = min(current_shares, recommended_reduce_shares)
```

- [ ] **Step 3: Add correlation haircut**

If portfolio analytics says `risk_concentration == "high"`, reduce BUY target shares by 50%.

If a ticker is in the max-correlation pair and the other ticker is already above 10% of assets, add `correlation_concentration` veto for new BUY.

- [ ] **Step 4: Add optimizer tests**

Test cases:

- BUY is capped by 20% max position
- BUY is capped by 2% risk budget
- BUY is capped by available cash
- high correlation halves BUY size
- margin expiry creates urgency veto
- SELL never exceeds current shares

- [ ] **Step 5: Run optimizer tests**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q ~/.claude/skills/stock-advisor/scripts/tests/test_portfolio_optimizer.py
```

Expected:

```text
6 passed
```

---

### Task 6: Add Cross-Sectional Factor Ranking

**Files:**
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/factor_engine.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_cross_sectional_factors.py`

- [ ] **Step 1: Add universe-level factor function**

Add:

```python
def compute_cross_sectional_factors(tickers: list[str]) -> dict:
```

Output:

```json
{
  "universe_size": 8,
  "ranked": [
    {
      "ticker": "7974.T",
      "composite_rank": 1,
      "composite_percentile": 0.875,
      "factor_scores": {
        "value": 0.2,
        "momentum": 1.1,
        "quality": 0.6,
        "volatility": -0.1
      }
    }
  ],
  "warnings": []
}
```

- [ ] **Step 2: Keep fallback behavior**

When universe has fewer than 3 tickers, keep the existing fixed reference median behavior and add:

```json
{"warning": "cross_sectional_universe_too_small"}
```

- [ ] **Step 3: Add tests**

Use monkeypatched factor raw data to verify:

- ranks are deterministic
- missing factor does not crash
- fewer than 3 tickers returns fallback warning
- higher composite percentile maps to stronger factor signal

---

### Task 7: Add Quant Decision Engine

**Files:**
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/quant_decision_engine.py`
- Create: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts/tests/test_quant_decision_engine.py`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`
- Modify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/skills/stock-report/SKILL.md`

- [ ] **Step 1: Add CLI**

CLI:

```bash
quant_decision_engine.py \
  --portfolio ~/code/playground/stock-price-analyze/portfolio.yaml \
  --signals "$RESULTS_DIR/signals.json" \
  --backtest-dir "$RESULTS_DIR/backtest" \
  --portfolio-analytics "$RESULTS_DIR/portfolio_analytics.json" \
  --output "$RESULTS_DIR/quant_decisions.json"
```

- [ ] **Step 2: Decision algorithm**

Algorithm order:

1. Load current holdings and account assets.
2. Load signals, factor scores, backtest metrics, and portfolio analytics.
3. Compute shrunk probability and EV after cost per active rule.
4. Add reliability vetoes.
5. Convert binary/factor signal into preliminary action.
6. Apply portfolio optimizer for target/order shares.
7. Enforce SELL limit order rule.
8. Emit `QuantDecision` objects.

- [ ] **Step 3: Action mapping**

Rules:

- `negative_ev` always maps to `NO_TRADE` unless action is risk-reducing SELL.
- `negative_walk_forward` maps BUY to `NO_TRADE`.
- `overfit_walk_forward` lowers confidence by one level.
- `low_sample` lowers confidence by one level.
- factor STRONG_SELL plus binary SELL maps to SELL.
- factor BUY plus binary HOLD maps to HOLD unless EV is positive and portfolio optimizer allows BUY.
- SELL/PARTIAL_SELL must use limit order.

- [ ] **Step 4: Add tests**

Test cases:

- positive EV BUY produces BUY with shares > 0
- negative EV BUY becomes NO_TRADE
- risk-reducing SELL survives negative EV
- SELL without limit is rejected by schema validation
- high correlation veto prevents new BUY
- low sample lowers confidence

- [ ] **Step 5: Update SKILL workflow**

Add Step 2d after portfolio analytics:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/quant_decision_engine.py \
  --portfolio ~/code/playground/stock-price-analyze/portfolio.yaml \
  --signals "$RESULTS_DIR/signals.json" \
  --backtest-dir "$RESULTS_DIR/backtest" \
  --portfolio-analytics "$RESULTS_DIR/portfolio_analytics.json" \
  -o "$RESULTS_DIR/quant_decisions.json"
```

- [ ] **Step 6: Update report instruction**

Update `stock-report/SKILL.md`:

```markdown
Final trade actions must come from `quant_decisions.json`. Do not upgrade HOLD/NO_TRADE into BUY or SELL in prose. If the LLM narrative disagrees with quant_decisions, show it as a caveat, not as the action.
```

---

### Task 8: End-To-End Verification

**Files:**
- Verify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/scripts`
- Verify: `/Users/fujie/.dotfiles/claude/skills/stock-advisor/SKILL.md`

- [ ] **Step 1: Syntax check**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python -m py_compile \
  ~/.claude/skills/stock-advisor/scripts/signal_engine.py \
  ~/.claude/skills/stock-advisor/scripts/backtest_engine.py \
  ~/.claude/skills/stock-advisor/scripts/trade_advisor.py \
  ~/.claude/skills/stock-advisor/scripts/factor_engine.py \
  ~/.claude/skills/stock-advisor/scripts/portfolio_analytics.py \
  ~/.claude/skills/stock-advisor/scripts/quant_schema.py \
  ~/.claude/skills/stock-advisor/scripts/signal_reliability.py \
  ~/.claude/skills/stock-advisor/scripts/portfolio_optimizer.py \
  ~/.claude/skills/stock-advisor/scripts/quant_decision_engine.py
```

Expected: exit code 0.

- [ ] **Step 2: Run all stock-advisor tests**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  -m pytest -q ~/.claude/skills/stock-advisor/scripts/tests
```

Expected: all tests pass.

- [ ] **Step 3: Run CLI smoke checks**

Run:

```bash
~/.claude/skills/stock-advisor/scripts/run_signal_engine --help
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/quant_decision_engine.py --help
```

Expected: both commands print argparse help and exit 0.

- [ ] **Step 4: Run one offline fixture test**

Create fixture files under:

```text
~/.claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/
```

The fixture must include:

- `portfolio.yaml`
- `signals.json`
- `backtest/7203.T.json`
- `portfolio_analytics.json`

Run:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/quant_decision_engine.py \
  --portfolio ~/.claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/portfolio.yaml \
  --signals ~/.claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/signals.json \
  --backtest-dir ~/.claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/backtest \
  --portfolio-analytics ~/.claude/skills/stock-advisor/scripts/tests/fixtures/quant_decision/portfolio_analytics.json \
  -o /tmp/quant_decisions.json
python3 -m json.tool /tmp/quant_decisions.json >/dev/null
```

Expected: valid JSON and at least one decision row.

---

## Suggested Implementation Order

1. Task 1: verification path cleanup
2. Task 2: schema
3. Task 3: reliability and expected value
4. Task 5: portfolio optimizer
5. Task 7: quant decision engine
6. Task 4: execution delay workflow integration
7. Task 6: cross-sectional factor ranking
8. Task 8: end-to-end verification

Reason: schema, EV, and optimizer create the smallest useful deterministic layer first. Cross-sectional factors are valuable but less urgent than making current signals tradable under risk constraints.

## Out Of Scope

- Automatic order placement to SBI証券.
- Intraday strategy or day trading.
- Machine learning model training.
- Alternative data ingestion beyond current yfinance/SBI/analyst fields.
- Public cloud deployment.

## Final Review Criteria

- `quant_decisions.json` exists and is the only source for final action labels.
- BUY actions have positive EV after cost and no hard veto.
- SELL/PARTIAL_SELL actions always include limit price.
- Order shares respect 100-share lot size, 20% position cap, 2% risk budget, and available cash.
- Low-sample and overfit signals reduce confidence or block new risk.
- Existing 68 stock-advisor tests still pass, and new tests cover every new module.
