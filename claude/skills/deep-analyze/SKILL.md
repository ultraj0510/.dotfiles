---
name: deep-analyze
description: 1銘柄に対してマルチエージェント深堀分析を実行
when_to_use: 「深堀分析して」「この銘柄詳しく見て」「deep analyze」または /deep-analyze 実行時
---

# deep-analyze — マルチエージェント深堀分析

指定銘柄を多角的に分析する。数値計算は stock-advisor パイプライン、解釈は LLM。

## パイプライン構成

```
数値分析（Python — stock-advisor パイプライン流用）
  ├ シグナル検出（signal_engine）
  ├ バックテスト（backtest_engine）
  ├ USピア比較（peer_comparison）
  └ 価格ゾーン＋追い証（price_zone_calculator）
    ↓
LLM分析（Claude）
  ├ Web検索で最新ニュース・アナリスト評価を取得
  ├ 全データを解釈し構造化レポート生成
  └ FINAL_DECISION 出力
```

## 手順

### 1. 数値分析実行

```bash
cd ~/.claude/skills/deep-analyze
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  pipeline/run_deep_analyze.py <TICKER>
```

### 2. LLM深堀分析

Claude が以下のデータを読み込み分析:
- `report_context.json`（1銘柄分の全数値データ集約）
- Web 検索で最新ニュース・アナリスト評価を取得
- ユーザーの取引スタイルに合わせた判断を出力

### 3. 結果確認

- `FINAL_DECISION` ブロックのアクション・価格・数量を確認
- `decision.json` に構造化判断を保存

## オプション

- `--language English` : 英語出力
- `--output-dir <path>` : 出力先変更

## 注記

TradingAgents v0.2.5 フレームワークは非推奨（依存未解決のため）。
本スキルは LLM ベースの代替実装を使用する。

TradingAgents 復活時は `pipeline/adapters.py` を差し替えて元のパイプラインに戻せる。
