---
name: stock-ir-fetch
description: Use when the user explicitly names stock-ir-fetch or asks to fetch and persist official Japanese company IR documents. Retrieves one TSE ticker's approved IR site documents as structured JSON with version tracking. Do not use for TDnet/EDINET, technical analysis, or buy/sell advice.
---

# stock-ir-fetch

日本株1銘柄の承認済み企業公式IRサイトから、文書を安全に差分同期し、原本・抽出テキスト・版履歴を保存する。

## 呼び出し

```text
stock-ir-fetch <ticker> [--refresh] [--data-dir PATH] [--approve-source ID] [--approve-source-url URL]
```

## 動作

- 未承認 → Yahoo Financeから候補を発見し `confirmation_required` を返す
- 承認済み → 初回3年・通常90日の差分同期
- 静的HTML限定、JSサイトは `unsupported`

## 実行

```bash
~/.dotfiles/claude/skills/stock-ir-fetch/scripts/fetch_stock_ir 285A
```

## 出力

- 標準出力: JSONのみ
- `status`: `success`, `partial`, `failed`, `confirmation_required`, `unsupported`

## 禁止事項

- TDnet/EDINETを取得元にしない
- 企業分析・売買判断を行わない
- ブラウザ自動操作をしない
