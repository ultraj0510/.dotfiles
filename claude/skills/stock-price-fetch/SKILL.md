---
name: stock-price-fetch
description: Use when the user explicitly names stock-price-fetch or asks to fetch and persist Japanese stock price history. Retrieves one TSE ticker's daily and recent hourly OHLCV as JSON. Do not use for technical analysis, scoring, portfolio decisions, or buy/sell advice.
---

# stock-price-fetch

日本株1銘柄の株価時系列を取得し、構造化JSONとして保存・出力する。

## 呼び出し

```text
stock-price-fetch <ticker> [--refresh] [--data-dir PATH]
```

## 取得範囲

- 初回: 日足5年、1時間足60日
- 通常再実行: 保存済み最終バー以降の差分
- 配当または株式分割の検知時: 日足5年を再照合

## 実行

```bash
~/.dotfiles/claude/skills/stock-price-fetch/scripts/fetch_stock_price 285A
```

## 出力

- 標準出力: JSONのみ
- 標準エラー: 安全なログと警告
- `status`: `success`、`partial`、`failed`
- `summary.usable`: 分析入力として最低限利用可能か

## 禁止事項

- テクニカル指標を計算しない
- 売買シグナルを生成しない
- 企業評価を行わない
- ポートフォリオ情報を扱わない
- 取得エラーを空の成功として返さない
