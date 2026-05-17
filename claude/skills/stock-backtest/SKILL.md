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
cd /Users/fujie/code/playground/stock-price-analyze
.venv/bin/python main.py backtest <TICKER>
```

タイムアウト: 60秒

### 2. 結果表示

- トレード履歴と損益推移を表示
- 生成されたレポートの要点を日本語でまとめる
