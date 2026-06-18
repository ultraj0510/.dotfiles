---
name: portfolio-fetch
description: Use when SBI証券から保有銘柄・口座情報をJSONとして取得する。テクニカル分析・売買判断は stock-advisor を使用。
---

# portfolio-fetch — SBI証券 Raw Data Fetch

SBI証券画面から保有銘柄・口座情報を取得し、事実データをJSONで出力する。

## 責務

- SBI証券HTMLを取得する
- HTMLから `holdings` と `account` を抽出する
- JSONを標準出力へ出す
- `~/code/playground/stock-price-analyze/portfolio.yaml` を更新する

## 非責務

テクニカル分析、シグナル判定、売買判断、スコアリング、レポート生成は行わない。分析が必要な場合は `stock-advisor` を使用する。

## 正本データ源

URL・UA・エンコーディング詳細は `references/data-sources.md`、出力スキーマは `references/schema.md`。

## コマンド

```bash
# SBIから取得してJSON出力 + portfolio.yaml更新
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio

# SBIに接続せず、既存portfolio.yamlをJSON出力
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio --skip-sync

# SBI取得失敗時にキャッシュJSONを出力
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio --use-cache-on-fail
```

## 出力

標準出力はJSONのみ。`[AUTH_EXPIRED]`, `[ERROR]`, `[NOTICE]`, `[WARN]` は標準エラーへ。

## Gotchas

- **モバイルUA 0件parse:** SBIがモバイルUAに保有銘柄を返さない場合、自動で desktop UA に retry する。
- **Cookie期限切れ:** `auth_expired` 時は exit 2。`portfolio-auth` でCookieを再取得する。
- **マージ安全ガード:** 既存 `portfolio.yaml` との統合時、SBI取得件数が既存の50%未満または3件以上欠損する場合はマージを中止し `parse_error` を返す。
- **Playwright不在:** urllib に fallback する。一部ページ構造の差異により parse 精度が低下する可能性がある。

## 完了証拠

- 正常系: stdout が valid JSON + exit 0 + `holdings` 配列が空でない + `portfolio.yaml` 更新
- キャッシュ系: stdout が valid JSON + exit 0 + `cache_used: true`
- 認証切れ: stderr に `[AUTH_EXPIRED]` + exit 2
