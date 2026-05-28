---
name: portfolio-analytics
description: ポートフォリオ全体の相関分析・ストレステストの実行と解釈。
---

# portfolio-analytics — ポートフォリオ分析

## 実行

```bash
~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
  ~/.claude/skills/stock-advisor/scripts/portfolio_analytics.py \
  --portfolio ~/code/playground/stock-price-analyze/portfolio.yaml \
  -o "$RESULTS_DIR/portfolio_analytics.json"
```

## 相関行列の解釈

| avg_correlation | 判定 | 対応 |
|-----------------|------|------|
| > 0.5 | **高** (リスク集中) | ポジション分散を検討 |
| 0.3〜0.5 | **中** | モニタリング継続 |
| < 0.3 | **低** | 分散効果あり |

- `max_correlation`: 最も相関の高いペア — この2銘柄は同じ方向に動く可能性が高い
- 相関 > 0.7 のペアがあれば、実質的に同じポジションの重複賭け

## ストレステストの解釈

| シナリオ | 市場下落率 | 評価 |
|----------|-----------|------|
| 2008_GFC | -48% | 最大級の金融危機 |
| 2020_COVID | -31% | パンデミックショック |
| 2024_Aug_JP | -20% | 日本独自の金利ショック |

- `loss_pct`: ポートフォリオ全体の推定損失率
- `worst_holdings`: シナリオ下で最大の損失が予想される上位3銘柄
- 損失率が30%を超えるシナリオがあれば、ポジション縮小を検討
- レポートでは最大シナリオ損失を明記すること
