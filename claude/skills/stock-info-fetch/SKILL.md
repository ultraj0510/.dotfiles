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

2026-06-20実接続検証完了。

- 自動テスト: 134 passed, 1 skipped
- 認証付き実接続スモーク: PASS (ticker=3932)
  - price: not_available（市場時間外）、company_profile: ok
  - stock_reports: not_available（graph.sbisec.co.jpはReact SPAのため静的取得不可）
  - 2回目実行: cache.hit=true、1回目とsections一致
  - stdout、stderr、キャッシュに認証値・秘密パラメータ漏洩なし

## 実行

```bash
~/.dotfiles/claude/skills/stock-info-fetch/scripts/fetch_stock_info 3932
```
