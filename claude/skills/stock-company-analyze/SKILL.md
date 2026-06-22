---
name: stock-company-analyze
description: Run full Japanese stock analysis — acquisition, evidence pack, TradingAgents multi-agent analysis, rating
---

# stock-company-analyze

日本株1銘柄の公式IR・株価・SBI企業情報を取得し、TradingAgentsで多面的分析・Bull/Bear討論を実行し、決定的ルールで最終レーティングを算出する。

## 呼び出し

`stock-company-analyze <ticker> [--resume RUN_ID] [--data-dir PATH]`

## 出力

- 標準出力: JSON only (analysis.json schema 1.0)
- `rating.final`: BUY / HOLD / SELL / SHORT / NOT_RATED
- `confidence.level`: High / Medium / Low
- `provisional`: true if evidence incomplete

## 実行

`~/.dotfiles/claude/skills/stock-company-analyze/scripts/stock_company_analyze 285A`
