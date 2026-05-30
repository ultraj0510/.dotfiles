---
name: stock-advisor
description: 日本株ポートフォリオ分析スキル。保有株式の含み損益・テクニカル指標・信用期限を自動取得し、今日の取引推奨を提示する。
when_to_use: 「株式分析」「朝のチェック」「ポートフォリオ確認」「今日の相場どう？」「保有株を確認」または /stock-advisor 実行時
---

## 役割

日本株ポートフォリオ分析アシスタント。データを取得し、**今日実行すべき取引を明確な指示形式で出力する**。

## 参照スキル

分析時は以下の子スキルの知識を参照すること（`Skill` ツールで読み込み不要、内容は常時適用）:

| スキル | 内容 |
|--------|------|
| **stock-signals** | シグナル判定基準、トレンド状態、スコアリング |
| **stock-report** | レポートテンプレート、分析原則、マクロ/アナリスト解釈 |
| **stock-risk** | 口座ルール（単元株）、信用取引ルール、期限アラート |
| **portfolio-analytics** | 相関行列、ストレステストの実行と解釈 |

## 手順

### Step 0: 初回セットアップ

```bash
~/.claude/skills/stock-advisor/scripts/setup_env
~/.claude/skills/stock-advisor/scripts/run_signal_engine --help
```

stock-advisor tests must run through `scripts/.venv/bin/python`; system Python may not have `numpy`, `pandas`, or `yfinance`.

### 前提条件

**`portfolio-fetch` を事前に実行済みであること。** 本スキルでは portfolio 取得を行わない。

```bash
# 事前に手動で実行:
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio
```

`portfolio.yaml` が最新化されていることを確認してから本スキルを実行する。

### Step 1: 結果ディレクトリ準備 + 注目銘柄 読込

```bash
RESULTS_DIR=~/code/playground/stock-price-analyze/results/$(date +%F)
mkdir -p "$RESULTS_DIR/backtest"
ln -sfn "$RESULTS_DIR" ~/code/playground/stock-price-analyze/results/latest
cat ~/.claude/skills/stock-advisor/watchlist.yaml 2>/dev/null || echo "No watchlist"
```

### Step 2: 数値シグナル検出

```bash
~/.claude/skills/stock-advisor/scripts/run_signal_engine --all --output "$RESULTS_DIR/signals.json"
```

### Step 2b: バックテスト

```bash
LATEST_TRADING_DAY=$(python3 -c "import json; d=json.load(open('$RESULTS_DIR/signals.json')); print(d.get('reference_date',''))")
for t in $(python3 -c "import yaml,os; d=yaml.safe_load(open(os.path.expanduser('~/code/playground/stock-price-analyze/portfolio.yaml'))); print(' '.join(sorted(set(h['ticker'] for h in d.get('holdings',[])))))"); do
  ~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
    ~/.claude/skills/stock-advisor/scripts/backtest_engine.py --ticker "$t" \
    --strategy default --execution-delay --end "$LATEST_TRADING_DAY" -o "$RESULTS_DIR/backtest/$t.json"
done
# 注目銘柄も同様 (watchlist.yaml)
```

### Step 2c: ポートフォリオ分析

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/portfolio_analytics.py \
  --portfolio ~/code/playground/stock-price-analyze/portfolio.yaml \
  -o "$RESULTS_DIR/portfolio_analytics.json"
```

### Step 2d: クオンツ意思決定

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/quant_decision_engine.py \
  --portfolio ~/code/playground/stock-price-analyze/portfolio.yaml \
  --signals "$RESULTS_DIR/signals.json" \
  --backtest-dir "$RESULTS_DIR/backtest" \
  --portfolio-analytics "$RESULTS_DIR/portfolio_analytics.json" \
  -o "$RESULTS_DIR/quant_decisions.json"
```

### Step 2e: レポート用コンテキスト生成

以下を実行し、レポート生成には `report_context.json` を唯一の入力コンテキストとして使う:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/report_context_builder.py \
  --portfolio ~/code/playground/stock-price-analyze/portfolio.yaml \
  --signals "$RESULTS_DIR/signals.json" \
  --backtest-dir "$RESULTS_DIR/backtest" \
  --portfolio-analytics "$RESULTS_DIR/portfolio_analytics.json" \
  --quant-decisions "$RESULTS_DIR/quant_decisions.json" \
  -o "$RESULTS_DIR/report_context.json"
```

レポート提出前に以下を実行する:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/validate_report.py \
  --report "$RESULTS_DIR/report.md" \
  --signals "$RESULTS_DIR/signals.json" \
  --quant-decisions "$RESULTS_DIR/quant_decisions.json" \
  --backtest-dir "$RESULTS_DIR/backtest"
```

### Step 3: レポート生成

以下のデータを読み込み、**stock-report** スキルの形式で最終レポートを出力:

1. `report_context.json` — 正規化済みコンテキスト（アクション・数量・シグナル名・WF判定・口座ラベル）
2. `signals.json` — シグナル・トレンド・スコア・アナリスト評価
3. `backtest/*.json` — VaR/CVaR・Sharpe CI・WF判定
4. `portfolio_analytics.json` — 相関行列・ストレステスト損失率
5. `quant_decisions.json` — クオンツ最終判断（期待値・veto・注文数量）

分析判断には **stock-signals** のシグナル・スコアリングルール、**stock-risk** の信用期限ルールを適用すること。

レポートは Write ツールで `$RESULTS_DIR/report.md` に保存。

**検証**: レポート保存後、以下でポジション数が portfolio.yaml と一致するか確認:
```bash
echo "portfolio.yaml: $(python3 -c "import yaml; print(len(yaml.safe_load(open('$HOME/code/playground/stock-price-analyze/portfolio.yaml'))['holdings']))") positions"
grep -c '^####\|^### .* — .*（.*%）' "$RESULTS_DIR/report.md" | tail -1
```

### 後処理

```bash
find ~/code/playground/stock-price-analyze/results -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null
```

## 取引後の portfolio.yaml 更新

```bash
~/.claude/skills/portfolio-update/scripts/update_portfolio buy 7974.T 100 8600 --type 現物
~/.claude/skills/portfolio-update/scripts/update_portfolio sell 1515.T 500 2603 --type 信用
~/.claude/skills/portfolio-update/scripts/update_portfolio show
```
