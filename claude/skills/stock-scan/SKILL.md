---
name: stock-scan
description: 全保有銘柄のシグナルスキャン。RSI/MACD/BBの3シグナルを判定し要アクション順に出力
when_to_use: 「スキャンして」「シグナル出てる銘柄は？」「全銘柄チェック」または /stock-scan 実行時
---

# stock-scan — シグナルスキャン

全保有銘柄（または指定範囲）のテクニカルシグナルを一覧出力する。

## 手順

### 1. スキャン実行

```bash
# 全銘柄シグナルスキャン（default_tickers.txt 使用）
~/.claude/skills/stock-advisor/scripts/run_signal_engine --all --output /tmp/stock_scan.json

# 特定銘柄のみ
~/.claude/skills/stock-advisor/scripts/run_signal_engine --tickers <TICKER1>,<TICKER2> --output /tmp/stock_scan.json
```

または直接Pythonで:

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/signal_engine.py --all --output /tmp/stock_scan.json
```

タイムアウト: 300秒（全銘柄分）

### 2. 結果表示

- シグナルが出た銘柄の一覧と各シグナルの内容を表示
- 判定基準は `signal-criteria.md` ルール参照
