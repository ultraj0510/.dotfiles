---
name: deep-analyze
description: 1銘柄に対して7エージェント×多段議論の深堀分析を実行。TradingAgents v0.2.5 日本語対応版
when_to_use: 「深堀分析して」「この銘柄詳しく見て」「deep analyze」または /deep-analyze 実行時
---

# deep-analyze — マルチエージェント深堀分析

TradingAgents v0.2.5 の日本語対応版パイプラインを使用し、1銘柄を多角的に分析する。

## パイプライン構成

```
4 analysts (market/fundamentals/sentiment/news)
    ↓
bull/bear debate（研究マネージャー統括）
    ↓
trader（トレードプラン生成）
    ↓
3-way risk debate（bull/bear/neutral）
    ↓
portfolio manager（最終判断 + 構造化出力）
```

## TradingAgents v0.2.5 対応

- 全7エージェント日本語出力 (`output_language: "Japanese"`)
- Pydantic 構造化出力（ResearchPlan, TraderProposal, PortfolioDecision）
- Memory Log: 同一 ticker の過去判断を次回分析に注入
- DeepSeek V4: `DeepSeekChatOpenAI` で thinking mode 対応

## 手順

### 1. 分析実行

```bash
cd ~/.claude/skills/deep-analyze
python pipeline/run_deep_analyze.py <TICKER>
```

タイムアウト: 300秒（全パイプライン分）

### 2. 結果確認

- `FINAL_DECISION` ブロックのアクション・価格を確認
- 出力ディレクトリに `decision.json`（構造化データ）が保存される
- memory log に今回の判断が追記される（次回同銘柄分析時に参照）

## オプション

- `--language English` : 英語出力に切り替え
- `--output-dir <path>` : 出力先を変更
