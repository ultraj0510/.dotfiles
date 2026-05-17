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
cd /Users/fujie/code/playground/stock-price-analyze

# 要アクション銘柄のみ
.venv/bin/python main.py scan

# 全銘柄レポート
.venv/bin/python main.py scan --all
```

タイムアウト: 300秒（全銘柄分）

### 2. 結果表示

- シグナルが出た銘柄の一覧と各シグナルの内容を表示
- 判定基準は `signal-criteria.md` ルール参照
