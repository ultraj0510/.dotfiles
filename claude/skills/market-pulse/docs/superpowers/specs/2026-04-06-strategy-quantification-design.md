# 投資戦略の数値化・チューニング設計

**日付:** 2026-04-06  
**対象:** morning-check スキル  
**目的:** ハードコードされた閾値をスコアリングエンジンに置き換え、設定ファイルで調整可能にし、実績データを蓄積してウェイトを自動最適化する

---

## 概要

現在の `needs_action()` はシグナルの発火可否を二値判定しているが、これをシグナルごとの**加重スコア**に変え、マクロ環境による乗数補正を加えた**adjusted_score** で行動判断を行う。実績は CSV に蓄積し、`tune_strategy.py` が勝率・期待値を分析してウェイトの更新案を推薦する。

---

## アーキテクチャ

```
morning-check/
├── portfolio.yaml           （既存：口座・保有情報）
├── strategy.yaml            （新規：シグナル設定・ウェイト・閾値）
├── scripts/
│   ├── fetch_portfolio.py   （既存：データ取得。スコア計算・CSV保存を追加）
│   ├── update_portfolio.py  （既存：取引記録。trade_log 記録を追加）
│   ├── score_engine.py      （新規：スコア計算ロジック）
│   └── tune_strategy.py     （新規：実績分析・ウェイト自動推薦）
└── data/
    ├── daily_scores.csv     （新規：日次スナップショット）
    └── trade_log.csv        （新規：取引時スコア紐付けログ）
```

**データフロー:**
1. `fetch_portfolio.py` が metrics を計算
2. `score_engine.py` が `strategy.yaml` を読み、raw_score → adjusted_score を算出
3. `daily_scores.csv` に自動保存（毎朝）
4. スコア付きで LLM エージェントに渡す
5. 取引実行時に `update_portfolio.py` が `trade_log.csv` に記録
6. `tune_strategy.py` が実績を分析してウェイト更新案を推薦

---

## strategy.yaml スキーマ

```yaml
version: 1

signals:
  # テクニカル（score: 正=強気, 負=弱気）
  rsi_oversold:    { score: +20, threshold: 35 }   # RSI ≤ threshold
  rsi_overbought:  { score: -20, threshold: 68 }   # RSI ≥ threshold
  bb_lower_touch:  { score: +15, threshold: 0.02 } # 現在値が BB下限の2%以内
  bb_upper_touch:  { score: -15, threshold: 0.02 } # 現在値が BB上限の2%以内
  w52_low:         { score: +10, threshold: 15 }   # 52週位置 ≤ 15%
  w52_high:        { score: -10, threshold: 85 }   # 52週位置 ≥ 85%
  momentum_surge:  { score: +12, threshold: 7.0 }  # 直近5日 +7%超

  # ファンダメンタル
  analyst_upside:  { score: +15, threshold: 25 }   # アナリスト目標比 +25%以上
  analyst_downside:{ score: -15, threshold: -15 }  # アナリスト目標比 -15%以下
  short_squeeze:   { score: +8,  threshold: 10 }   # 空売りFloat比率 ≥ 10%

  # ポジション管理
  pnl_loss:        { score: -25, threshold: -15 }  # 含み損 ≤ -15%
  pnl_profit:      { score: +20, threshold: 30 }   # 含み益 ≥ 30%

macro_multipliers:
  vix_risk_off:  { multiplier: 0.6, threshold: 25 }   # VIX ≥ 25 → BUYスコアを60%に減衰
  vix_risk_on:   { multiplier: 1.2, threshold: 13 }   # VIX ≤ 13 → スコアを1.2倍
  sp500_down:    { multiplier: 0.7, threshold: -1.5 }  # S&P500前日 ≤ -1.5%
  sp500_up:      { multiplier: 1.1, threshold: 1.0 }   # S&P500前日 ≥ +1.0%
  usdjpy_strong: { multiplier: 1.1, threshold: 155 }   # USD/JPY ≥ 155（初期は全銘柄に適用）
  usdjpy_weak:   { multiplier: 0.9, threshold: 140 }   # USD/JPY ≤ 140（初期は全銘柄に適用）

action_thresholds:
  buy:         +25   # adjusted_score ≥ +25 → BUY検討
  sell:        -25   # adjusted_score ≤ -25 → SELL検討
  action_flag: +15   # |adjusted_score| ≥ 15 → 要アクション（エージェント分析対象）
```

---

## スコア計算ロジック（score_engine.py）

1. 各シグナルの発火チェック → 点数を合算 → `raw_score`
2. マクロ環境を評価して乗数を決定（複数該当時は積算）
3. 正のシグナル（強気）にのみ乗数を適用 → `adjusted_score`
   - 弱気シグナルは乗数の影響を受けない（リスク管理の非対称性）
4. `action_flag = abs(adjusted_score) >= action_thresholds.action_flag`
5. 信用ポジションの残日数 < 60日は `action_flag=True` を強制（スコア不問）

**後方互換:** `strategy.yaml` が存在しない場合は既存の `needs_action()` ロジックにフォールバック

---

## データ記録スキーマ

### daily_scores.csv

```
date, ticker, raw_score, adjusted_score, macro_multiplier, signals_fired,
current_price, rsi, bb_pos, w52_pos, action_flag
```

- 毎朝 `fetch_portfolio.py` 実行時に全保有銘柄分を追記
- `signals_fired`: カンマ区切りのシグナル名リスト

### trade_log.csv

```
date, ticker, action, quantity, price,
score_at_entry, signals_at_entry,
exit_date, exit_price, score_at_exit, pnl_pct, pnl_jpy
```

- `update_portfolio.py` でBUY時に記録（exit系は空欄）
- SELL時に同一 ticker の最新 BUY レコードに exit 情報を追記

---

## tune_strategy.py の動作

```
python3 scripts/tune_strategy.py [--min-trades 10] [--apply]
```

**処理:**
1. `trade_log.csv` からクローズ済み取引を抽出
2. シグナル別に勝率・平均 PnL・発火回数を集計
3. 勝率が低いシグナルはウェイト引き下げ、高いシグナルは引き上げを推薦
4. `--apply` なし（デフォルト）: 推薦内容を表示して手動確認を促す
5. `--apply` あり: `strategy.yaml` を自動更新

**最低サンプル数 (`--min-trades`):** デフォルト 10件未満のシグナルは推薦をスキップ（統計的信頼性の確保）

---

## 既存ファイルへの変更

| ファイル | 変更内容 |
|---------|---------|
| `fetch_portfolio.py` | `score_engine.py` を import してスコア算出・表示・CSV追記を追加 |
| `update_portfolio.py` | BUY/SELL 実行時に `trade_log.csv` へスコア付き記録を追加 |

---

## 未解決事項

- なし（仕様は確定）

---

## 実装順序

1. `strategy.yaml` の作成
2. `score_engine.py` の実装
3. `fetch_portfolio.py` への統合（スコア表示・daily_scores.csv 保存）
4. `update_portfolio.py` への統合（trade_log.csv 記録）
5. `tune_strategy.py` の実装
6. 動作確認
