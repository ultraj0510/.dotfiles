---
name: portfolio-fetch
description: 全保有銘柄のテクニカル指標・シグナル・信用リスクを一括取得
when_to_use: 「保有銘柄を見て」「ポートフォリオ確認」「今日の評価額」または portfolio-fetch 明示呼出時
---

# portfolio-fetch — 保有銘柄データ取得

stock-price-analyze の分析モジュールで全保有銘柄のテクニカル指標・シグナル・信用リスクを一括計算する。

## 前提

- stock-price-analyze が `~/code/playground/stock-price-analyze/` に存在すること
- `portfolio.yaml` が同ディレクトリに存在すること
- `SBI_COOKIE` 環境変数が設定されていれば、SBIからポートフォリオ自動同期後にデータ取得する

## 手順

```bash
# 要アクション銘柄のみ（デフォルト。SBI同期失敗時は非0終了）
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio

# 全銘柄詳細
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio --all

# SBI自動同期をスキップ
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio --skip-sync

# SBI同期失敗時にキャッシュ表示を続行
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio --use-cache-on-fail
```

実行後は先頭3行を必ず確認し、`[AUTH_EXPIRED]`, `[ERROR]`, `[NOTICE]`, `[WARN]` があれば同期状態を判断する。

## 出力

- Portfolio Snapshot（日付 + 総資産 + 現金残高）
- Macro Context（VIX, S&P500前日比 + データ鮮度）
- 要アクション銘柄一覧（スコア順、テクニカル指標・シグナル・信用リスク付き）
