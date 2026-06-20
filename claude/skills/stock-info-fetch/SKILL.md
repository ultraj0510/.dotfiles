---
name: stock-info-fetch
description: Use when the user explicitly says「銘柄情報を取得 <4桁コード>」or explicitly names stock-info-fetch to retrieve one Japanese stock's SBI facts as JSON. Do not use for portfolio retrieval, technical analysis, scoring, or buy/sell advice.
---

# stock-info-fetch

SBI証券の国内株式銘柄画面から、投資判断に必要な事実データを7セクション（株価、企業概要、企業スコア、業績、ニュース、適時開示、STOCK REPORTS）取得し、分析や売買判断を加えずに構造化JSONとして返す。

## 呼び出し

```
stock-info-fetch <ticker> [--refresh] [--cache-dir PATH]
```

例:
```
stock-info-fetch 3932
stock-info-fetch 7203 --refresh
```

## 出力

標準出力にJSONのみを出力。ログ・警告・進捗は標準エラー出力。

## キャッシュ

日本時間の日付単位でキャッシュ。同日2回目以降はキャッシュから返す。`--refresh` で再取得。

## 認証

`portfolio-auth` のCookieストア (`~/.config/sbi-portfolio/tokens.json`) を読み取り専用で利用。
Cookie切れの場合は `auth_expired` エラーを返す。

## 実行

```bash
~/.dotfiles/claude/skills/stock-info-fetch/scripts/fetch_stock_info 3932
```

## 完了証拠

- 自動テストが全件PASS（102+件）
- 認証付き実接続スモーク (`RUN_SBI_SMOKE=1`) がPASS
- `price`と`company_profile`が有用データを持つ
- STOCK REPORTSの表構造が期間・単位付きで取得できる
- 2回目実行が検証済みcache hitになる (`cache.hit=true`)
- stdout、stderr、キャッシュに認証値・秘密パラメータが含まれない
