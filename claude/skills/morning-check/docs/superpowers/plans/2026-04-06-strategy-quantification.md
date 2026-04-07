# Strategy Quantification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** morning-check の投資判断をスコアリングエンジンに置き換え、`strategy.yaml` で閾値・ウェイトを調整でき、実績データ（daily_scores.csv / trade_log.csv）を蓄積して `tune_strategy.py` で自動最適化できるようにする。

**Architecture:** `score_engine.py` がピュアな scoring ロジックと CSV I/O を担う。`fetch_portfolio.py` は scoring 結果を使って `needs_action()` を置き換え、毎朝 `daily_scores.csv` に追記する。`update_portfolio.py` は取引実行時に `trade_log.csv` にスコアを紐付けて記録する。`tune_strategy.py` が実績を分析してウェイト更新を推薦する。

**Tech Stack:** Python 3.11+, pyyaml, pandas (tune_strategy のみ), pytest

---

## ファイルマップ

| ファイル | 操作 | 責務 |
|---------|------|------|
| `strategy.yaml` | 新規作成 | シグナル設定・マクロ乗数・判定閾値 |
| `scripts/score_engine.py` | 新規作成 | スコア計算ロジック + CSV I/O |
| `scripts/fetch_portfolio.py` | 修正 | score_engine 統合・daily_scores.csv 追記 |
| `scripts/update_portfolio.py` | 修正 | trade_log.csv 記録 |
| `scripts/tune_strategy.py` | 新規作成 | 実績分析・ウェイト推薦 |
| `tests/conftest.py` | 新規作成 | pytest パス設定 |
| `tests/test_score_engine.py` | 新規作成 | score_engine のユニットテスト |
| `tests/test_tune_strategy.py` | 新規作成 | tune_strategy のユニットテスト |
| `data/daily_scores.csv` | 自動生成 | 日次スナップショット |
| `data/trade_log.csv` | 自動生成 | 取引実績ログ |

---

## Task 1: strategy.yaml と data/ ディレクトリを作成する

**Files:**
- Create: `strategy.yaml`
- Create: `data/.gitkeep`

- [ ] **Step 1: strategy.yaml を作成する**

```yaml
# strategy.yaml
# スコア: 正=強気(BUY方向), 負=弱気(SELL方向)
# threshold: シグナル発火条件の閾値
version: 1

signals:
  # ── テクニカル ──────────────────────────────────────────────────
  rsi_oversold:    { score: 20,  threshold: 35   }  # RSI ≤ threshold
  rsi_overbought:  { score: -20, threshold: 68   }  # RSI ≥ threshold
  bb_lower_touch:  { score: 15,  threshold: 0.02 }  # (current - bb_lower)/bb_lower ≤ threshold
  bb_upper_touch:  { score: -15, threshold: 0.02 }  # (bb_upper - current)/bb_upper ≤ threshold
  w52_low:         { score: 10,  threshold: 15   }  # 52週位置 ≤ threshold (%)
  w52_high:        { score: -10, threshold: 85   }  # 52週位置 ≥ threshold (%)
  momentum_surge:  { score: 12,  threshold: 7.0  }  # 直近5日騰落率 ≥ threshold (%)

  # ── ファンダメンタル ────────────────────────────────────────────
  analyst_upside:   { score: 15,  threshold: 25  }  # アナリスト目標比 ≥ threshold (%)
  analyst_downside: { score: -15, threshold: -15 }  # アナリスト目標比 ≤ threshold (%)
  short_squeeze:    { score: 8,   threshold: 10  }  # 空売りFloat比率 ≥ threshold (%)

  # ── ポジション管理 ──────────────────────────────────────────────
  pnl_loss:   { score: -25, threshold: -15 }  # 含み損率 ≤ threshold (%)
  pnl_profit: { score: 20,  threshold: 30  }  # 含み益率 ≥ threshold (%)

# マクロ補正乗数（正のスコアにのみ適用）
# 複数条件が重なる場合は積算
macro_multipliers:
  vix_risk_off:  { multiplier: 0.6, threshold: 25   }  # VIX ≥ threshold
  vix_risk_on:   { multiplier: 1.2, threshold: 13   }  # VIX ≤ threshold
  sp500_down:    { multiplier: 0.7, threshold: -1.5 }  # S&P500前日変化率 ≤ threshold (%)
  sp500_up:      { multiplier: 1.1, threshold: 1.0  }  # S&P500前日変化率 ≥ threshold (%)
  usdjpy_strong: { multiplier: 1.1, threshold: 155  }  # USD/JPY ≥ threshold
  usdjpy_weak:   { multiplier: 0.9, threshold: 140  }  # USD/JPY ≤ threshold

# アクション判定閾値
action_thresholds:
  buy:         25   # adjusted_score ≥ buy  → BUY検討
  sell:        -25  # adjusted_score ≤ sell → SELL検討
  action_flag: 15   # |adjusted_score| ≥ action_flag → 要アクション（エージェント分析対象）
```

- [ ] **Step 2: data/ ディレクトリを確認する**

```bash
ls /Users/fujie/.claude/skills/morning-check/data/
```

Expected: ディレクトリが存在する（前のステップで作成済み）

---

## Task 2: テスト基盤と failing tests を作成する

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_score_engine.py`

- [ ] **Step 1: conftest.py を作成する**

```python
# tests/conftest.py
import sys
import os

# morning-check/ ディレクトリを Python パスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
```

- [ ] **Step 2: test_score_engine.py を作成する**

```python
# tests/test_score_engine.py
import os
import csv
import tempfile
import pytest
from scripts.score_engine import (
    load_strategy,
    compute_macro_multiplier,
    score_holding,
    append_daily_scores,
    read_latest_score,
    record_trade_entry,
    record_trade_exit,
)

# ── テスト用フィクスチャ ─────────────────────────────────────────

MINIMAL_STRATEGY = {
    "version": 1,
    "signals": {
        "rsi_oversold":    {"score": 20,  "threshold": 35},
        "rsi_overbought":  {"score": -20, "threshold": 68},
        "bb_lower_touch":  {"score": 15,  "threshold": 0.02},
        "bb_upper_touch":  {"score": -15, "threshold": 0.02},
        "w52_low":         {"score": 10,  "threshold": 15},
        "w52_high":        {"score": -10, "threshold": 85},
        "momentum_surge":  {"score": 12,  "threshold": 7.0},
        "analyst_upside":  {"score": 15,  "threshold": 25},
        "analyst_downside":{"score": -15, "threshold": -15},
        "short_squeeze":   {"score": 8,   "threshold": 10},
        "pnl_loss":        {"score": -25, "threshold": -15},
        "pnl_profit":      {"score": 20,  "threshold": 30},
    },
    "macro_multipliers": {
        "vix_risk_off":  {"multiplier": 0.6, "threshold": 25},
        "vix_risk_on":   {"multiplier": 1.2, "threshold": 13},
        "sp500_down":    {"multiplier": 0.7, "threshold": -1.5},
        "sp500_up":      {"multiplier": 1.1, "threshold": 1.0},
        "usdjpy_strong": {"multiplier": 1.1, "threshold": 155},
        "usdjpy_weak":   {"multiplier": 0.9, "threshold": 140},
    },
    "action_thresholds": {"buy": 25, "sell": -25, "action_flag": 15},
}

NEUTRAL_MACRO = {
    "^VIX":     {"latest": 18.0, "change_1d": 0.5},
    "^GSPC":    {"latest": 5000, "change_1d": 0.3},
    "USDJPY=X": {"latest": 148.0},
}

RISK_OFF_MACRO = {
    "^VIX":     {"latest": 30.0, "change_1d": 5.0},
    "^GSPC":    {"latest": 4800, "change_1d": -2.5},
    "USDJPY=X": {"latest": 148.0},
}

# ── load_strategy ──────────────────────────────────────────────

def test_load_strategy_returns_defaults_when_missing():
    result = load_strategy("/nonexistent/path/strategy.yaml")
    assert "signals" in result
    assert "rsi_oversold" in result["signals"]
    assert "action_thresholds" in result

def test_load_strategy_reads_file(tmp_path):
    import yaml
    s = {"version": 1, "signals": {"rsi_oversold": {"score": 99, "threshold": 40}},
         "macro_multipliers": {}, "action_thresholds": {"buy": 10, "sell": -10, "action_flag": 5}}
    p = tmp_path / "strategy.yaml"
    p.write_text(yaml.dump(s))
    result = load_strategy(str(p))
    assert result["signals"]["rsi_oversold"]["score"] == 99

# ── compute_macro_multiplier ────────────────────────────────────

def test_compute_macro_multiplier_neutral():
    m = compute_macro_multiplier(NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert m == pytest.approx(1.0)

def test_compute_macro_multiplier_vix_risk_off():
    m = compute_macro_multiplier(RISK_OFF_MACRO, MINIMAL_STRATEGY)
    # VIX≥25 → 0.6, S&P500≤-1.5% → 0.7  →  0.6 * 0.7 = 0.42
    assert m == pytest.approx(0.42)

def test_compute_macro_multiplier_vix_risk_on():
    macro = {"^VIX": {"latest": 10.0, "change_1d": -1.0},
             "^GSPC": {"latest": 5000, "change_1d": 0.2},
             "USDJPY=X": {"latest": 148.0}}
    m = compute_macro_multiplier(macro, MINIMAL_STRATEGY)
    assert m == pytest.approx(1.2)

# ── score_holding ───────────────────────────────────────────────

def test_score_holding_rsi_oversold():
    holding  = {"ticker": "7974.T", "cost_price": 10000, "position_type": "現物"}
    metrics  = {"current": 9800, "rsi": 28.0, "pos_52w": 50.0,
                "ret_5d": 1.0, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
                "notable": []}
    analyst  = {}
    result   = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert "rsi_oversold" in result["signals_fired"]
    assert result["raw_score"] == 20

def test_score_holding_macro_reduces_positive_score():
    holding  = {"ticker": "7974.T", "cost_price": 10000, "position_type": "現物"}
    metrics  = {"current": 9800, "rsi": 28.0, "pos_52w": 50.0,
                "ret_5d": 1.0, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
                "notable": []}
    analyst  = {}
    neutral  = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    risk_off = score_holding(holding, metrics, analyst, RISK_OFF_MACRO, MINIMAL_STRATEGY)
    assert risk_off["adjusted_score"] < neutral["adjusted_score"]
    assert risk_off["macro_multiplier"] == pytest.approx(0.42)

def test_score_holding_multiple_signals():
    holding  = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "現物"}
    # RSI 28 (oversold +20), 52週位置 10% (w52_low +10), 含み損 -20% (pnl_loss -25)
    metrics  = {"current": 8000, "rsi": 28.0, "pos_52w": 10.0,
                "ret_5d": 1.0, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
                "notable": []}
    analyst  = {}
    result   = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert "rsi_oversold" in result["signals_fired"]
    assert "w52_low" in result["signals_fired"]
    assert "pnl_loss" in result["signals_fired"]
    assert result["raw_score"] == 20 + 10 - 25  # = +5

def test_score_holding_action_flag_above_threshold():
    holding  = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "現物"}
    # RSI 28 +20, w52_low +10 → raw=30, adjusted=30 (neutral macro) → action_flag=True
    metrics  = {"current": 9800, "rsi": 28.0, "pos_52w": 10.0,
                "ret_5d": 1.0, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
                "notable": []}
    analyst  = {}
    result   = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert result["action_flag"] is True

def test_score_holding_credit_under_60_days_forces_action_flag():
    from datetime import date, timedelta
    expiry = (date.today() + timedelta(days=30)).isoformat()
    holding = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "信用",
               "expiry_date": expiry}
    metrics = {"current": 10100, "rsi": 50.0, "pos_52w": 50.0,
               "ret_5d": 0.5, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
               "notable": []}
    analyst = {}
    result  = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert result["action_flag"] is True  # 残30日なので強制 True

def test_score_holding_credit_over_60_days_no_forced_flag():
    from datetime import date, timedelta
    expiry = (date.today() + timedelta(days=90)).isoformat()
    holding = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "信用",
               "expiry_date": expiry}
    metrics = {"current": 10100, "rsi": 50.0, "pos_52w": 50.0,
               "ret_5d": 0.5, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
               "notable": []}
    analyst = {}
    result  = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    # スコアは低い（発火なし）→ action_flag は False
    assert result["action_flag"] is False

def test_score_holding_empty_metrics_returns_zero():
    holding = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "現物"}
    result  = score_holding(holding, {}, {}, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert result["raw_score"] == 0
    assert result["signals_fired"] == []
    assert result["action_flag"] is False

# ── CSV I/O ─────────────────────────────────────────────────────

def test_append_and_read_daily_scores(tmp_path):
    data_dir = str(tmp_path)
    holdings_scores = [
        {
            "date": "2026-04-06",
            "ticker": "7974.T",
            "position_type": "現物",
            "raw_score": 30,
            "adjusted_score": 25.0,
            "macro_multiplier": 1.0,
            "signals_fired": "rsi_oversold,w52_low",
            "current_price": 9800,
            "rsi": 28.0,
            "bb_pos": 0.05,
            "w52_pos": 12.0,
            "action_flag": True,
        }
    ]
    append_daily_scores(holdings_scores, data_dir)
    result = read_latest_score("7974.T", "現物", data_dir)
    assert result is not None
    assert float(result["adjusted_score"]) == pytest.approx(25.0)
    assert result["signals_fired"] == "rsi_oversold,w52_low"

def test_read_latest_score_returns_none_when_no_data(tmp_path):
    result = read_latest_score("9999.T", "現物", str(tmp_path))
    assert result is None

def test_record_trade_entry_and_exit(tmp_path):
    data_dir = str(tmp_path)
    score_data = {"adjusted_score": 28.0, "signals_fired": "rsi_oversold"}
    record_trade_entry(
        date="2026-04-06", ticker="7974.T", action="BUY",
        qty=100, price=9800.0, position_type="現物",
        cost_price=9800.0, score_data=score_data, data_dir=data_dir
    )
    record_trade_exit(
        ticker="7974.T", position_type="現物",
        exit_date="2026-05-10", exit_price=10500.0, exit_qty=100,
        data_dir=data_dir
    )
    log_path = os.path.join(data_dir, "trade_log.csv")
    with open(log_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["exit_price"] == "10500.0"
    assert float(rows[0]["pnl_pct"]) == pytest.approx((10500.0 / 9800.0 - 1) * 100)
```

- [ ] **Step 3: テストが FAIL することを確認する**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 -m pytest tests/test_score_engine.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'load_strategy' from 'scripts.score_engine'`（ファイル未作成のため）

---

## Task 3: score_engine.py を実装してテストを通す

**Files:**
- Create: `scripts/score_engine.py`

- [ ] **Step 1: score_engine.py を作成する**

```python
# scripts/score_engine.py
"""
score_engine.py — シグナルスコアリングエンジン + CSV I/O

外部依存: pyyaml のみ（yfinance 不要）
"""
import os
import csv
from datetime import date, datetime

try:
    import yaml
except ImportError:
    yaml = None  # フォールバック用

# ── デフォルト戦略（strategy.yaml がない場合のフォールバック） ──
DEFAULT_STRATEGY = {
    "version": 1,
    "signals": {
        "rsi_oversold":    {"score": 20,  "threshold": 35},
        "rsi_overbought":  {"score": -20, "threshold": 68},
        "bb_lower_touch":  {"score": 15,  "threshold": 0.02},
        "bb_upper_touch":  {"score": -15, "threshold": 0.02},
        "w52_low":         {"score": 10,  "threshold": 15},
        "w52_high":        {"score": -10, "threshold": 85},
        "momentum_surge":  {"score": 12,  "threshold": 7.0},
        "analyst_upside":  {"score": 15,  "threshold": 25},
        "analyst_downside":{"score": -15, "threshold": -15},
        "short_squeeze":   {"score": 8,   "threshold": 10},
        "pnl_loss":        {"score": -25, "threshold": -15},
        "pnl_profit":      {"score": 20,  "threshold": 30},
    },
    "macro_multipliers": {
        "vix_risk_off":  {"multiplier": 0.6, "threshold": 25},
        "vix_risk_on":   {"multiplier": 1.2, "threshold": 13},
        "sp500_down":    {"multiplier": 0.7, "threshold": -1.5},
        "sp500_up":      {"multiplier": 1.1, "threshold": 1.0},
        "usdjpy_strong": {"multiplier": 1.1, "threshold": 155},
        "usdjpy_weak":   {"multiplier": 0.9, "threshold": 140},
    },
    "action_thresholds": {"buy": 25, "sell": -25, "action_flag": 15},
}

DAILY_SCORES_FILENAME = "daily_scores.csv"
TRADE_LOG_FILENAME = "trade_log.csv"

DAILY_SCORES_FIELDS = [
    "date", "ticker", "position_type", "raw_score", "adjusted_score",
    "macro_multiplier", "signals_fired", "current_price",
    "rsi", "bb_pos", "w52_pos", "action_flag",
]

TRADE_LOG_FIELDS = [
    "date", "ticker", "action", "quantity", "price", "position_type", "cost_price",
    "score_at_entry", "signals_at_entry",
    "exit_date", "exit_price", "exit_quantity", "pnl_pct", "pnl_jpy",
]


def load_strategy(strategy_path: str) -> dict:
    """
    strategy.yaml を読み込む。ファイルが存在しない場合は DEFAULT_STRATEGY を返す。
    """
    if not os.path.isfile(strategy_path) or yaml is None:
        return DEFAULT_STRATEGY
    try:
        with open(strategy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data or "signals" not in data:
            return DEFAULT_STRATEGY
        return data
    except Exception:
        return DEFAULT_STRATEGY


def compute_macro_multiplier(macro: dict, strategy: dict) -> float:
    """
    マクロ市場データからスコア補正乗数を計算する。
    複数条件が重なる場合は積算。VIX は risk_off/risk_on の両方を同時適用しない。

    macro の期待キー:
      "^VIX"     → {"latest": float}
      "^GSPC"    → {"change_1d": float}
      "USDJPY=X" → {"latest": float}
    """
    mults = strategy.get("macro_multipliers", {})
    multiplier = 1.0

    vix = macro.get("^VIX", {}).get("latest")
    if vix is not None:
        if "vix_risk_off" in mults and vix >= mults["vix_risk_off"]["threshold"]:
            multiplier *= mults["vix_risk_off"]["multiplier"]
        elif "vix_risk_on" in mults and vix <= mults["vix_risk_on"]["threshold"]:
            multiplier *= mults["vix_risk_on"]["multiplier"]

    sp500_chg = macro.get("^GSPC", {}).get("change_1d")
    if sp500_chg is not None:
        if "sp500_down" in mults and sp500_chg <= mults["sp500_down"]["threshold"]:
            multiplier *= mults["sp500_down"]["multiplier"]
        elif "sp500_up" in mults and sp500_chg >= mults["sp500_up"]["threshold"]:
            multiplier *= mults["sp500_up"]["multiplier"]

    usdjpy = macro.get("USDJPY=X", {}).get("latest")
    if usdjpy is not None:
        if "usdjpy_strong" in mults and usdjpy >= mults["usdjpy_strong"]["threshold"]:
            multiplier *= mults["usdjpy_strong"]["multiplier"]
        elif "usdjpy_weak" in mults and usdjpy <= mults["usdjpy_weak"]["threshold"]:
            multiplier *= mults["usdjpy_weak"]["multiplier"]

    return round(multiplier, 4)


def _check_signal(name: str, metrics: dict, analyst: dict, holding: dict, signals: dict) -> bool:
    """
    1シグナルの発火チェック。True = 発火。
    """
    if name not in signals:
        return False
    cfg = signals[name]
    thr = cfg["threshold"]
    cur = metrics.get("current")

    if name == "rsi_oversold":
        rsi = metrics.get("rsi")
        return rsi is not None and rsi <= thr
    if name == "rsi_overbought":
        rsi = metrics.get("rsi")
        return rsi is not None and rsi >= thr
    if name == "bb_lower_touch":
        bb_lower = metrics.get("bb_lower")
        return (cur is not None and bb_lower is not None and bb_lower > 0
                and (cur - bb_lower) / bb_lower <= thr)
    if name == "bb_upper_touch":
        bb_upper = metrics.get("bb_upper")
        return (cur is not None and bb_upper is not None and bb_upper > 0
                and (bb_upper - cur) / bb_upper <= thr)
    if name == "w52_low":
        p = metrics.get("pos_52w")
        return p is not None and p <= thr
    if name == "w52_high":
        p = metrics.get("pos_52w")
        return p is not None and p >= thr
    if name == "momentum_surge":
        r5 = metrics.get("ret_5d")
        return r5 is not None and r5 >= thr
    if name == "analyst_upside":
        tm = analyst.get("target_mean")
        return (cur is not None and tm is not None and cur > 0
                and (tm / cur - 1) * 100 >= thr)
    if name == "analyst_downside":
        tm = analyst.get("target_mean")
        return (cur is not None and tm is not None and cur > 0
                and (tm / cur - 1) * 100 <= thr)
    if name == "short_squeeze":
        sp = analyst.get("short_pct")
        return sp is not None and sp >= thr
    if name == "pnl_loss":
        cost = holding.get("cost_price")
        return (cur is not None and cost is not None and cost > 0
                and (cur / cost - 1) * 100 <= thr)
    if name == "pnl_profit":
        cost = holding.get("cost_price")
        return (cur is not None and cost is not None and cost > 0
                and (cur / cost - 1) * 100 >= thr)
    return False


def score_holding(holding: dict, metrics: dict, analyst: dict,
                  macro: dict, strategy: dict) -> dict:
    """
    1保有のスコアを計算する。

    Returns:
        {
            "raw_score": int,
            "adjusted_score": float,
            "macro_multiplier": float,
            "signals_fired": list[str],
            "action_flag": bool,
        }
    """
    if not metrics:
        return {
            "raw_score": 0, "adjusted_score": 0.0,
            "macro_multiplier": 1.0, "signals_fired": [], "action_flag": False,
        }

    signals = strategy.get("signals", {})
    thresholds = strategy.get("action_thresholds", DEFAULT_STRATEGY["action_thresholds"])

    fired = []
    positive_score = 0
    negative_score = 0

    for name, cfg in signals.items():
        if _check_signal(name, metrics, analyst, holding, signals):
            fired.append(name)
            s = cfg["score"]
            if s > 0:
                positive_score += s
            else:
                negative_score += s

    raw_score = positive_score + negative_score
    macro_mult = compute_macro_multiplier(macro, strategy)
    adjusted_score = round(positive_score * macro_mult + negative_score, 2)

    # 信用ポジションの残日数 < 60日 は強制 True
    action_flag = abs(adjusted_score) >= thresholds.get("action_flag", 15)
    if holding.get("position_type") == "信用" and holding.get("expiry_date"):
        days_left = (datetime.strptime(holding["expiry_date"], "%Y-%m-%d").date()
                     - date.today()).days
        if days_left < 60:
            action_flag = True

    return {
        "raw_score": raw_score,
        "adjusted_score": adjusted_score,
        "macro_multiplier": macro_mult,
        "signals_fired": fired,
        "action_flag": action_flag,
    }


# ── CSV I/O ──────────────────────────────────────────────────────

def _ensure_csv(path: str, fields: list[str]):
    """CSV がなければヘッダー付きで作成する。"""
    if not os.path.isfile(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def append_daily_scores(holdings_scores: list[dict], data_dir: str):
    """
    holdings_scores: score_holding の結果と銘柄情報をまとめた dict のリスト。
    各 dict のキーは DAILY_SCORES_FIELDS に対応する。
    """
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, DAILY_SCORES_FILENAME)
    _ensure_csv(path, DAILY_SCORES_FIELDS)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DAILY_SCORES_FIELDS, extrasaction="ignore")
        for row in holdings_scores:
            w.writerow(row)


def read_latest_score(ticker: str, position_type: str, data_dir: str) -> dict | None:
    """
    daily_scores.csv から ticker + position_type の最新行を返す。
    データがなければ None。
    """
    path = os.path.join(data_dir, DAILY_SCORES_FILENAME)
    if not os.path.isfile(path):
        return None
    latest = None
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ticker"] == ticker and row["position_type"] == position_type:
                latest = row
    return latest


def record_trade_entry(date: str, ticker: str, action: str, qty: int, price: float,
                        position_type: str, cost_price: float,
                        score_data: dict, data_dir: str):
    """
    BUY/SELL 実行時にスコア付きで trade_log.csv に追記する。
    score_data: {"adjusted_score": float, "signals_fired": str or list}
    """
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, TRADE_LOG_FILENAME)
    _ensure_csv(path, TRADE_LOG_FIELDS)

    signals = score_data.get("signals_fired", "")
    if isinstance(signals, list):
        signals = ",".join(signals)

    row = {
        "date": date, "ticker": ticker, "action": action,
        "quantity": qty, "price": price, "position_type": position_type,
        "cost_price": cost_price,
        "score_at_entry": score_data.get("adjusted_score", ""),
        "signals_at_entry": signals,
        "exit_date": "", "exit_price": "", "exit_quantity": "", "pnl_pct": "", "pnl_jpy": "",
    }
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS).writerow(row)


def record_trade_exit(ticker: str, position_type: str, exit_date: str,
                       exit_price: float, exit_qty: int, data_dir: str):
    """
    SELL 実行時に、該当 ticker + position_type の最新オープン BUY エントリに exit 情報を書き込む。
    """
    path = os.path.join(data_dir, TRADE_LOG_FILENAME)
    if not os.path.isfile(path):
        return

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # 最新のオープン BUY エントリを探す（exit_date が空）
    target_idx = None
    for i in range(len(rows) - 1, -1, -1):
        r = rows[i]
        if (r["ticker"] == ticker and r["position_type"] == position_type
                and r["action"] == "BUY" and not r["exit_date"]):
            target_idx = i
            break

    if target_idx is None:
        return  # 対応する BUY が見つからない場合はスキップ

    entry = rows[target_idx]
    cost = float(entry["cost_price"]) if entry["cost_price"] else float(entry["price"])
    pnl_pct = (exit_price / cost - 1) * 100
    pnl_jpy = (exit_price - cost) * exit_qty

    rows[target_idx].update({
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_quantity": exit_qty,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_jpy": round(pnl_jpy, 0),
    })

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)
```

- [ ] **Step 2: テストを実行してすべて PASS することを確認する**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 -m pytest tests/test_score_engine.py -v
```

Expected（全テスト PASS）:
```
tests/test_score_engine.py::test_load_strategy_returns_defaults_when_missing PASSED
tests/test_score_engine.py::test_load_strategy_reads_file PASSED
tests/test_score_engine.py::test_compute_macro_multiplier_neutral PASSED
tests/test_score_engine.py::test_compute_macro_multiplier_vix_risk_off PASSED
tests/test_score_engine.py::test_compute_macro_multiplier_vix_risk_on PASSED
tests/test_score_engine.py::test_score_holding_rsi_oversold PASSED
tests/test_score_engine.py::test_score_holding_macro_reduces_positive_score PASSED
tests/test_score_engine.py::test_score_holding_multiple_signals PASSED
tests/test_score_engine.py::test_score_holding_action_flag_above_threshold PASSED
tests/test_score_engine.py::test_score_holding_credit_under_60_days_forces_action_flag PASSED
tests/test_score_engine.py::test_score_holding_credit_over_60_days_no_forced_flag PASSED
tests/test_score_engine.py::test_score_holding_empty_metrics_returns_zero PASSED
tests/test_score_engine.py::test_append_and_read_daily_scores PASSED
tests/test_score_engine.py::test_read_latest_score_returns_none_when_no_data PASSED
tests/test_score_engine.py::test_record_trade_entry_and_exit PASSED
15 passed in X.XXs
```

- [ ] **Step 3: コミットする**

```bash
cd /Users/fujie/.claude/skills/morning-check
# git管理外のため手動確認のみ
echo "score_engine.py + tests created"
```

---

## Task 4: fetch_portfolio.py に score_engine を統合する

**Files:**
- Modify: `scripts/fetch_portfolio.py`

- [ ] **Step 1: ファイル先頭にインポートと定数を追加する**

`fetch_portfolio.py` の `PORTFOLIO_PATH = ...` の行（61行目付近）の直後に追加:

```python
STRATEGY_PATH = os.path.join(os.path.dirname(__file__), "..", "strategy.yaml")
DATA_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")

# score_engine をオプショナルインポート（存在しない場合は既存ロジックで動作）
try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__))
    from score_engine import load_strategy, score_holding, append_daily_scores
    _SCORE_ENGINE_AVAILABLE = True
except ImportError:
    _SCORE_ENGINE_AVAILABLE = False
```

- [ ] **Step 2: main() でスコアを計算する箇所を追加する**

`main()` 内の以下の行:
```python
    for t in tickers:
        data[t]["metrics"] = compute_metrics(data[t]["df"])
        data[t]["analyst"] = fetch_analyst_short_data(t)
```
の直後（`credit_h = ...` の前）に追加:

```python
    # ── スコアリング（score_engine が利用可能な場合） ─────────────────
    scores = {}  # key: (ticker, position_type) -> score_result
    if _SCORE_ENGINE_AVAILABLE:
        strategy = load_strategy(STRATEGY_PATH)
        for h in holdings:
            t = h["ticker"]
            result = score_holding(
                h, data[t]["metrics"], data[t]["analyst"], macro, strategy
            )
            scores[(t, h.get("position_type", "現物"))] = result
```

- [ ] **Step 3: needs_action() をスコアで置き換える**

`main()` 内の以下のブロック:
```python
        for h in spot_h:
            m = data[h["ticker"]]["metrics"]
            flag, reasons = needs_action(h, m, analyst=data[h["ticker"]]["analyst"])
            if flag:
                action_h.append((h, m, reasons))
            else:
                passive_h.append((h, m))
```
を以下に置き換える:

```python
        for h in spot_h:
            m = data[h["ticker"]]["metrics"]
            key = (h["ticker"], h.get("position_type", "現物"))
            if _SCORE_ENGINE_AVAILABLE and key in scores:
                sc = scores[key]
                flag = sc["action_flag"]
                reasons = sc["signals_fired"] + [
                    f"score={sc['adjusted_score']:+.0f}(raw={sc['raw_score']:+d}×{sc['macro_multiplier']})"
                ]
            else:
                flag, reasons = needs_action(h, m, analyst=data[h["ticker"]]["analyst"])
            if flag:
                action_h.append((h, m, reasons))
            else:
                passive_h.append((h, m))
```

- [ ] **Step 4: daily_scores.csv への保存を追加する**

`main()` の最後（`print("=" * 55)` の直前）に追加:

```python
    # ── daily_scores.csv への保存 ─────────────────────────────────
    if _SCORE_ENGINE_AVAILABLE and scores:
        today_str = datetime.today().strftime("%Y-%m-%d")
        rows = []
        for h in holdings:
            t    = h["ticker"]
            pt   = h.get("position_type", "現物")
            key  = (t, pt)
            sc   = scores.get(key, {})
            m    = data[t]["metrics"]
            rows.append({
                "date":             today_str,
                "ticker":           t,
                "position_type":    pt,
                "raw_score":        sc.get("raw_score", 0),
                "adjusted_score":   sc.get("adjusted_score", 0.0),
                "macro_multiplier": sc.get("macro_multiplier", 1.0),
                "signals_fired":    ",".join(sc.get("signals_fired", [])),
                "current_price":    m.get("current", ""),
                "rsi":              m.get("rsi", ""),
                "bb_pos":           (round((m["current"] - m["bb_lower"]) / m["bb_lower"], 4)
                                     if m.get("current") and m.get("bb_lower") else ""),
                "w52_pos":          m.get("pos_52w", ""),
                "action_flag":      sc.get("action_flag", False),
            })
        append_daily_scores(rows, DATA_DIR)
        print(f"  [スコア保存] {DATA_DIR}/daily_scores.csv に {len(rows)} 行追記")
```

- [ ] **Step 5: 動作確認する（データ取得あり）**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 scripts/fetch_portfolio.py 2>&1 | tail -20
```

Expected: 出力の末尾に `[スコア保存] .../data/daily_scores.csv に N 行追記` が表示される

- [ ] **Step 6: daily_scores.csv の内容を確認する**

```bash
cat /Users/fujie/.claude/skills/morning-check/data/daily_scores.csv
```

Expected: ヘッダー行 + 保有銘柄数分のデータ行

---

## Task 5: update_portfolio.py に trade_log 記録を追加する

**Files:**
- Modify: `scripts/update_portfolio.py`

- [ ] **Step 1: インポートと定数を追加する**

`update_portfolio.py` の `PORTFOLIO_PATH = ...` の行の直後に追加:

```python
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__))
    from score_engine import read_latest_score, record_trade_entry, record_trade_exit
    _SCORE_ENGINE_AVAILABLE = True
except ImportError:
    _SCORE_ENGINE_AVAILABLE = False
```

- [ ] **Step 2: cmd_buy() に trade_log 記録を追加する**

`cmd_buy()` の `save(portfolio)` 呼び出しの直後（`print(f"✅ ...")` の前）に追加:

```python
    if _SCORE_ENGINE_AVAILABLE:
        score_data = read_latest_score(ticker, position_type, DATA_DIR) or {}
        entry_score = {
            "adjusted_score": score_data.get("adjusted_score", ""),
            "signals_fired":  score_data.get("signals_fired", ""),
        }
        record_trade_entry(
            date=date.today().isoformat(), ticker=ticker, action="BUY",
            qty=qty, price=price, position_type=position_type,
            cost_price=price, score_data=entry_score, data_dir=DATA_DIR,
        )
```

- [ ] **Step 3: cmd_sell() に trade_log 記録を追加する**

`cmd_sell()` の `save(portfolio)` 呼び出しの直後に追加:

```python
    if _SCORE_ENGINE_AVAILABLE:
        record_trade_exit(
            ticker=ticker, position_type=position_type,
            exit_date=date.today().isoformat(),
            exit_price=price, exit_qty=qty, data_dir=DATA_DIR,
        )
```

- [ ] **Step 4: show サブコマンドに trade_log サマリを追加する**

`cmd_show()` の末尾（最後の `print` の後）に追加:

```python
    # trade_log サマリ
    log_path = os.path.join(DATA_DIR, "trade_log.csv")
    if os.path.isfile(log_path):
        import csv as _csv
        with open(log_path, newline="", encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        closed = [r for r in rows if r.get("exit_date")]
        if closed:
            wins = sum(1 for r in closed if float(r["pnl_pct"] or 0) > 0)
            print(f"\n取引実績: {len(closed)}件クローズ  勝率:{wins/len(closed)*100:.0f}%")
```

- [ ] **Step 5: 動作確認（dryrun）**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 scripts/update_portfolio.py show
```

Expected: 現在の保有一覧が表示される（エラーなし）

---

## Task 6: tune_strategy.py を実装してテストする

**Files:**
- Create: `scripts/tune_strategy.py`
- Create: `tests/test_tune_strategy.py`

- [ ] **Step 1: failing test を作成する**

```python
# tests/test_tune_strategy.py
import csv
import os
import pytest
import tempfile

def _write_trade_log(path, rows):
    fields = [
        "date", "ticker", "action", "quantity", "price", "position_type", "cost_price",
        "score_at_entry", "signals_at_entry",
        "exit_date", "exit_price", "exit_quantity", "pnl_pct", "pnl_jpy",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_analyze_returns_signal_stats(tmp_path):
    import sys
    skill_dir = os.path.dirname(os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(skill_dir, "scripts"))
    from tune_strategy import analyze_signals

    log = tmp_path / "trade_log.csv"
    _write_trade_log(str(log), [
        {"date": "2026-04-01", "ticker": "A.T", "action": "BUY", "quantity": 100,
         "price": 1000, "position_type": "現物", "cost_price": 1000,
         "score_at_entry": 30, "signals_at_entry": "rsi_oversold,w52_low",
         "exit_date": "2026-04-10", "exit_price": 1100, "exit_quantity": 100,
         "pnl_pct": 10.0, "pnl_jpy": 10000},
        {"date": "2026-04-02", "ticker": "B.T", "action": "BUY", "quantity": 100,
         "price": 2000, "position_type": "現物", "cost_price": 2000,
         "score_at_entry": 20, "signals_at_entry": "rsi_oversold",
         "exit_date": "2026-04-12", "exit_price": 1900, "exit_quantity": 100,
         "pnl_pct": -5.0, "pnl_jpy": -10000},
        {"date": "2026-04-03", "ticker": "C.T", "action": "BUY", "quantity": 100,
         "price": 3000, "position_type": "現物", "cost_price": 3000,
         "score_at_entry": 25, "signals_at_entry": "rsi_oversold,bb_lower_touch",
         "exit_date": "2026-04-15", "exit_price": 3300, "exit_quantity": 100,
         "pnl_pct": 10.0, "pnl_jpy": 30000},
    ])
    stats = analyze_signals(str(log), min_trades=1)
    # rsi_oversold: 3件 勝2負1 → 勝率0.667
    assert "rsi_oversold" in stats
    assert stats["rsi_oversold"]["trades"] == 3
    assert abs(stats["rsi_oversold"]["win_rate"] - 2/3) < 0.01
    # w52_low: 1件 勝1 → 勝率1.0
    assert "w52_low" in stats
    assert stats["w52_low"]["win_rate"] == pytest.approx(1.0)


def test_recommend_adjustments(tmp_path):
    skill_dir = os.path.dirname(os.path.dirname(__file__))
    import sys
    sys.path.insert(0, os.path.join(skill_dir, "scripts"))
    from tune_strategy import recommend_adjustments

    stats = {
        "rsi_oversold": {"trades": 12, "win_rate": 0.75, "avg_pnl": 5.0},  # 高勝率 → UP
        "w52_low":      {"trades": 10, "win_rate": 0.40, "avg_pnl": -1.0}, # 低勝率 → DOWN
        "bb_lower_touch": {"trades": 3, "win_rate": 0.60, "avg_pnl": 2.0}, # 少ない → skip (min=5)
    }
    recs = recommend_adjustments(stats, min_trades=5)
    tickers_rec = {r["signal"]: r["direction"] for r in recs}
    assert tickers_rec.get("rsi_oversold") == "up"
    assert tickers_rec.get("w52_low") == "down"
    assert "bb_lower_touch" not in tickers_rec  # min_trades 未満
```

- [ ] **Step 2: テストが FAIL することを確認する**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 -m pytest tests/test_tune_strategy.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'analyze_signals' from 'tune_strategy'`

- [ ] **Step 3: tune_strategy.py を実装する**

```python
#!/usr/bin/env python3
"""
tune_strategy.py — シグナル実績分析・ウェイト自動推薦

使い方:
  python3 scripts/tune_strategy.py                  # 分析して推薦を表示
  python3 scripts/tune_strategy.py --apply          # strategy.yaml を自動更新
  python3 scripts/tune_strategy.py --min-trades 5   # 最低サンプル数を変更（デフォルト10）
"""
import sys
import os
import csv
import argparse
from collections import defaultdict

SKILL_DIR     = os.path.dirname(os.path.dirname(__file__))
DATA_DIR      = os.path.join(SKILL_DIR, "data")
STRATEGY_PATH = os.path.join(SKILL_DIR, "strategy.yaml")
TRADE_LOG     = os.path.join(DATA_DIR, "trade_log.csv")

sys.path.insert(0, os.path.dirname(__file__))
from score_engine import load_strategy

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


def analyze_signals(trade_log_path: str, min_trades: int = 10) -> dict:
    """
    trade_log.csv を読み込み、シグナル別の実績統計を返す。
    Returns: {signal_name: {"trades": int, "win_rate": float, "avg_pnl": float}}
    """
    if not os.path.isfile(trade_log_path):
        return {}

    with open(trade_log_path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("exit_date")]  # クローズ済みのみ

    if not rows:
        return {}

    signal_data = defaultdict(list)
    for r in rows:
        pnl = r.get("pnl_pct", "")
        if not pnl:
            continue
        pnl_val = float(pnl)
        for sig in r.get("signals_at_entry", "").split(","):
            sig = sig.strip()
            if sig:
                signal_data[sig].append(pnl_val)

    stats = {}
    for sig, pnls in signal_data.items():
        if len(pnls) == 0:
            continue
        wins = sum(1 for p in pnls if p > 0)
        stats[sig] = {
            "trades":   len(pnls),
            "win_rate": wins / len(pnls),
            "avg_pnl":  round(sum(pnls) / len(pnls), 2),
        }
    return stats


def recommend_adjustments(stats: dict, min_trades: int = 10) -> list[dict]:
    """
    シグナル統計から strategy.yaml への調整推薦を生成する。
    Returns: [{"signal": str, "direction": "up"|"down", "reason": str}]
    """
    recs = []
    for sig, s in stats.items():
        if s["trades"] < min_trades:
            continue
        if s["win_rate"] >= 0.65:
            recs.append({"signal": sig, "direction": "up",
                          "reason": f"勝率{s['win_rate']*100:.0f}% ({s['trades']}件)"})
        elif s["win_rate"] <= 0.45:
            recs.append({"signal": sig, "direction": "down",
                          "reason": f"勝率{s['win_rate']*100:.0f}% ({s['trades']}件)"})
    return recs


def apply_adjustments(recs: list[dict], strategy_path: str):
    """
    推薦を strategy.yaml に反映する（既存スコアを±15%調整）。
    """
    if not _YAML_OK:
        print("ERROR: pyyaml が必要です。pip install pyyaml")
        return

    strategy = load_strategy(strategy_path)
    signals  = strategy.get("signals", {})
    changed  = []

    for rec in recs:
        sig = rec["signal"]
        if sig not in signals:
            continue
        old_score = signals[sig]["score"]
        if rec["direction"] == "up":
            new_score = round(old_score * 1.15)
        else:
            new_score = round(old_score * 0.85)
        if new_score != old_score:
            signals[sig]["score"] = new_score
            changed.append(f"  {sig}: {old_score} → {new_score}  ({rec['reason']})")

    if not changed:
        print("変更なし")
        return

    with open(strategy_path, "w", encoding="utf-8") as f:
        yaml.dump(strategy, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print("strategy.yaml を更新しました:")
    for c in changed:
        print(c)


def main():
    parser = argparse.ArgumentParser(description="シグナル実績分析・ウェイト推薦")
    parser.add_argument("--apply",      action="store_true", help="strategy.yaml を自動更新")
    parser.add_argument("--min-trades", type=int, default=10, help="最低トレード数 (default: 10)")
    args = parser.parse_args()

    print(f"trade_log: {TRADE_LOG}")
    stats = analyze_signals(TRADE_LOG, min_trades=args.min_trades)

    if not stats:
        print("クローズ済みトレードがありません。取引実績を蓄積してから再実行してください。")
        return

    print(f"\nシグナル別実績分析 (min_trades={args.min_trades})\n{'─'*55}")
    print(f"{'シグナル':<22} {'勝率':>6} {'平均PnL':>8} {'件数':>5}")
    print(f"{'─'*22} {'─'*6} {'─'*8} {'─'*5}")
    for sig, s in sorted(stats.items(), key=lambda x: -x[1]["win_rate"]):
        flag = " ↑推薦" if s["win_rate"] >= 0.65 else (" ↓推薦" if s["win_rate"] <= 0.45 else "")
        skip = "  (サンプル不足)" if s["trades"] < args.min_trades else ""
        print(f"{sig:<22} {s['win_rate']*100:>5.0f}% {s['avg_pnl']:>+7.1f}% {s['trades']:>5}{flag}{skip}")

    recs = recommend_adjustments(stats, min_trades=args.min_trades)

    if not recs:
        print("\n推薦なし（閾値を下げるには --min-trades を小さくしてください）")
        return

    print(f"\n推薦 strategy.yaml 更新案:")
    for r in recs:
        arrow = "↑ウェイト増" if r["direction"] == "up" else "↓ウェイト減"
        print(f"  {r['signal']:<22} {arrow}  {r['reason']}")

    if args.apply:
        apply_adjustments(recs, STRATEGY_PATH)
    else:
        print("\n※ 適用するには --apply オプションを付けて再実行してください")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: テストを実行して PASS することを確認する**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 -m pytest tests/test_tune_strategy.py -v
```

Expected:
```
tests/test_tune_strategy.py::test_analyze_returns_signal_stats PASSED
tests/test_tune_strategy.py::test_recommend_adjustments PASSED
2 passed in X.XXs
```

- [ ] **Step 5: 全テストを実行して PASS することを確認する**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 -m pytest tests/ -v
```

Expected: 17 passed

---

## Task 7: エンドツーエンド動作確認

- [ ] **Step 1: fetch_portfolio.py を実行してスコア出力を確認する**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 scripts/fetch_portfolio.py 2>&1 | grep -E "score|スコア|action_flag|要アクション"
```

Expected: `score=+XX` または `[スコア保存]` の行が含まれる

- [ ] **Step 2: daily_scores.csv を確認する**

```bash
python3 -c "
import csv
with open('data/daily_scores.csv') as f:
    rows = list(csv.DictReader(f))
for r in rows[:3]:
    print(r['ticker'], r['adjusted_score'], r['signals_fired'], r['action_flag'])
"
```

Expected: ticker ごとに adjusted_score と signals_fired が表示される

- [ ] **Step 3: tune_strategy.py を実行する（データ不足の確認）**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 scripts/tune_strategy.py
```

Expected: `クローズ済みトレードがありません。取引実績を蓄積してから再実行してください。`

- [ ] **Step 4: テスト用ダミーデータで tune_strategy.py の推薦機能を確認する**

```bash
cd /Users/fujie/.claude/skills/morning-check
python3 -c "
from scripts.tune_strategy import analyze_signals, recommend_adjustments
stats = {
    'rsi_oversold':   {'trades': 15, 'win_rate': 0.73, 'avg_pnl': 4.5},
    'w52_low':        {'trades': 12, 'win_rate': 0.42, 'avg_pnl': -1.2},
    'bb_lower_touch': {'trades': 10, 'win_rate': 0.60, 'avg_pnl': 2.1},
}
recs = recommend_adjustments(stats, min_trades=10)
for r in recs:
    print(r)
"
```

Expected:
```python
{'signal': 'rsi_oversold', 'direction': 'up',   'reason': '勝率73% (15件)'}
{'signal': 'w52_low',      'direction': 'down',  'reason': '勝率42% (12件)'}
```
