---
name: stock-backtest
description: 指定銘柄の過去シグナルに対するパフォーマンスを検証するバックテスト
when_to_use: 「バックテストして」「過去の成績見て」「検証して」または /stock-backtest 実行時
---

# stock-backtest — バックテスト

指定銘柄の過去シグナルに対するパフォーマンスを検証する。

## 手順

### 1. バックテスト実行

```bash
~/.claude/skills/stock-advisor/scripts/run_signal_engine backtest_engine.py --ticker <TICKER>
```

または直接Pythonで:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/backtest_engine.py --ticker <TICKER>
```

**オプション:**

| オプション | 説明 |
|-----------|------|
| `--ticker <TICKER>` | バックテスト対象銘柄（必須） |
| `--start YYYY-MM-DD` | 開始日（デフォルト: 1年前） |
| `--end YYYY-MM-DD` | 終了日（デフォルト: 直近営業日） |
| `--tune` | 4パラメータ（RSI下限/上限、52週位置下限/上限）のグリッドサーチを実行 |
| `--output <PATH>` | JSON出力先ファイルパス |

`--tune` 使用時は walk-forward分析（70% train / 30% test）で過剰適合を自動検出する。train/test間のSharpe ratio差が50%超またはtest Sharpeが負の場合、チューニング結果は破棄されデフォルト閾値が使用される。

タイムアウト: 300秒（--tune使用時は600秒）

### 2. 結果表示

- トレード履歴と損益推移を表示
- 生成されたレポートの要点を日本語でまとめる
