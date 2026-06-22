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
- 同一公式ドメインのIRトップ、IRニュース、IRライブラリーを静的HTMLで巡回する
- 動的E-IR部品は実行せず、`status=partial`と`coverage_complete=false`で通知する
- 静的HTML限定、JSサイトは `unsupported`

## カバレッジ

- 同一公式ドメインのIRトップ、IRニュース、IRライブラリーを静的HTMLで巡回する。
- 動的E-IR部品は実行せず、`status=partial`と`coverage_complete=false`で通知する。
- 公式IRページから禁止配信元へリンクされている文書は取得せず、件数と文書名だけを安全に通知する。
- `summary.usable`は保存済み文書を分析入力として利用できるかを示す。
- `summary.coverage_complete`は公式IR一覧を完全に確認できたかを示す。

## 実行

```bash
~/.dotfiles/claude/skills/stock-ir-fetch/scripts/fetch_stock_ir 285A
```

## 出力

- 標準出力: JSONのみ（schema 1.1）
- `status`: `success`, `partial`, `failed`, `confirmation_required`, `unsupported`
- `summary.usable`: 保存済み文書が存在するか
- `summary.coverage_complete`: 静的取得ですべてのIRリンクをカバーできたか
- `summary.prohibited_documents`: 禁止配信元のため取得しなかった文書数
- `summary.dynamic_pages`: 動的E-IR部品を含むページ数

## 禁止事項

- TDnet/EDINETを取得元にしない
- 企業分析・売買判断を行わない
- ブラウザ自動操作をしない

## 完了条件

- 自動テストが全件PASS
- 3932と285Aの初回・差分smokeがPASS
- 承認前にsource.jsonを保存しない
- 同一URL差替を新しいSHA-256版として保持する
- PDF/HTML抽出とOCR preflightがPASS
- 未対応サイトをunsupportedとして明示する
- 原本、manifest、stdoutに秘密値やローカル一時パスがない
