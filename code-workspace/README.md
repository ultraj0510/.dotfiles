# Stock Analysis Workspace

日本株ポートフォリオ分析・取引判断支援システム。

## システム概要

SBI証券の保有データ・株価・IR情報を収集し、テクニカル分析 × ファンダメンタル分析（LLM）の統合判断を毎営業日に生成する。

```
[SBI証券] ──Playwright──→ portfolio.yaml
[yfinance] ──────────────→ 株価・テクニカル指標
[企業IRサイト] ──────────→ IR文書

        ↓

stock-company-analyze（7-phase pipeline）
  ├── Phase 1-3: データ収集・証拠パック
  ├── Phase 4:   テクニカル分析（signal + backtest）
  ├── Phase 5:   ファンダメンタル分析（LLM: Bull/Bear討論・シナリオ・投資テーマ）
  ├── Phase 5b:  レーティング検証
  ├── Phase 6:   統合判断（ファンダメンタル × テクニカル 9-cell conflict matrix）
  └── Phase 7:   analysis.json v2.0 出力

        ↓

stock-advisor（daily runner）
  ├── run_daily_actions.py  →  daily_actions.json（3層判断 + ポートフォリオ制約）
  └── report_writer.py      →  report.md（朝レビュー用）
```

### 3層判断モデル

| 層 | 出力 | 決定者 |
|----|------|--------|
| investment_rating | BUY / HOLD / SELL | ファンダメンタル × テクニカル conflict matrix |
| execution_posture | ACT_NOW / WAIT / NO_TRADE | conflict matrix |
| order_candidates | 注文候補（数量・価格） | ポートフォリオ制約（保証金率・信用期限・集中度） |

## ディレクトリ構成

```
/Users/fujie/code/
├── README.md                    ← このファイル
├── CLAUDE.md                    ← Claude Code ワークスペースエントリポイント
├── workspace.md                 ← 共有ルール・エリアマップ（全ツール共通の信頼できる情報源）
├── workspace.toml               ← 機械可読パスマッピング
├── docs/                        ← 計画書・教訓・レビュー
│   └── superpowers/
│       ├── specs/               ← 設計仕様書
│       └── plans/               ← 実装計画
├── runtime/
│   └── stock-company-analysis/  ← 日次分析の出力（銘柄別 latest.json + runs/）
└── repo/                        ← 独立 git リポジトリ群
    ├── stock-price-analyze/     ← 分析コアモジュール
    └── tradingagents/           ← TradingAgents 実装

~/.dotfiles/claude/skills/
├── stock-advisor/               ← 毎朝のポートフォリオ分析ランナー
├── stock-company-analyze/       ← 1銘柄の深堀分析（テクニカル＋LLM）
├── stock-company-report/        ← analysis.json → HTML レポート生成
├── stock-company-monitor/       ← 登録銘柄のIRイベント平日監視
├── stock-scan/                  ← 全保有銘柄シグナルスキャン
├── stock-backtest/              ← 指定銘柄の過去シグナル検証
├── stock-price-fetch/           ← 株価データ取得
├── stock-ir-fetch/              ← IR文書取得
├── stock-info-fetch/            ← SBI企業情報取得
├── portfolio-fetch/             ← SBI証券からの保有・口座データ取得
├── portfolio-auth/              ← SBI証券セッションCookie管理
└── portfolio-update/            ← 売買記録・ポートフォリオ更新
```

## 毎朝のワークフロー

```bash
# 1. 認証（Cookie が切れている場合）
/portfolio-auth

# 2. 保有データ取得
/portfolio-fetch

# 3. 分析実行（全保有銘柄 + ウォッチリスト）
/stock-advisor

# 出力:
#   runtime/stock-company-analysis/{ticker}/runs/{run_id}/analysis.json
#   portfolio.yaml と同じディレクトリの daily_actions.json
#   report.md
```

### 単一銘柄の深堀分析

```bash
/stock-company-analyze 285A
# → runtime/stock-company-analysis/285A/runs/{run_id}/analysis.json
```

### ウォッチリスト

`~/.dotfiles/claude/skills/stock-advisor/watchlist.yaml`:

```yaml
- ticker: "7974.T"
  note: "任天堂"
- ticker: "4503.T"
  note: "アステラス製薬"
```

ウォッチリスト銘柄は保有がなくても分析され、`daily_actions.json` に `source: "watchlist"` で記録される。保有銘柄の分析失敗はエラー終了するが、ウォッチリストのみの失敗はエラー扱いしない。

## 主要ファイル

### 入力

| ファイル | 説明 |
|----------|------|
| `~/code/playground/stock-price-analyze/portfolio.yaml` | 保有銘柄・口座情報（portfolio-fetch が生成） |
| `~/.dotfiles/claude/skills/stock-advisor/watchlist.yaml` | ウォッチリスト（任意） |

### 出力（`runtime/stock-company-analysis/{ticker}/`）

| ファイル | 説明 |
|----------|------|
| `latest.json` | 最新 run へのポインタ（`latest_run_id`, `investment_rating`） |
| `runs/{run_id}/evidence_pack.json` | 収集データ（SBI情報・株価・IR文書） |
| `runs/{run_id}/analysis.json` | 分析結果 v2.0（technical, fundamental, integrated, forecast） |
| `runs/{run_id}/market_metrics.json` | 市場指標（TOPIX, 為替, VIX） |

### analysis.json v2.0 構造

```json
{
  "schema_version": "2.0",
  "ticker": "5803",
  "as_of": "2026-06-28T09:00:00+09:00",
  "technical": {
    "direction": "BUY",
    "signal_raw": "HOLD_BUY",
    "indicators": { "rsi": 55.2, "macd": {...}, "bollinger": {...}, "atr": 123.4 },
    "backtest": { "walk_forward": {...}, "var": {...} }
  },
  "fundamental": {
    "rating": "BUY",
    "scenarios": [{ "label": "強気", "probability": 0.4, "price_target": 7000 }, ...],
    "investment_thesis": "独自の光ファイバ技術でシェア拡大中...",
    "catalysts": ["2026-08 1Q決算"],
    "analyst_reports": { "bull": {...}, "bear": {...}, "portfolio_manager": {...} }
  },
  "integrated": {
    "investment_rating": "BUY",
    "execution_posture": "ACT_NOW",
    "reasoning": "ファンダメンタルBUY × テクニカルBUY → 積極買い",
    "risk_flags": []
  },
  "forecast": {
    "target": "next_session",
    "target_date": "2026-06-30",
    "ohlc": { "open": 6150, "high": 6280, "low": 6080, "close": 6220 },
    "bias": 1.15,
    "confidence": "medium"
  }
}
```

## スキル一覧

### メイン（毎日使う）

| スキル | 呼出 | 説明 |
|--------|------|------|
| stock-advisor | `/stock-advisor` | 全保有＋ウォッチリスト分析 → daily_actions.json + report.md |
| stock-company-analyze | `/stock-company-analyze <ticker>` | 1銘柄の深堀分析 → analysis.json |
| stock-scan | `/stock-scan` | 全保有銘柄のシグナル簡易スキャン |

### データ取得（通常は stock-advisor が内部呼出）

| スキル | 説明 |
|--------|------|
| portfolio-fetch | SBI証券から保有・口座データをJSON取得 |
| portfolio-auth | SBI証券セッションCookieの検証・保存 |
| stock-price-fetch | 株価履歴取得（yfinance） |
| stock-info-fetch | SBI企業情報取得 |
| stock-ir-fetch | 公式IR文書取得 |

### 補助

| スキル | 説明 |
|--------|------|
| stock-backtest | 指定銘柄の過去シグナルバックテスト |
| stock-company-report | analysis.json → HTML レポート生成 |
| stock-company-monitor | 登録銘柄のIRイベント平日監視（自動再分析） |
| portfolio-update | 売買記録・保有銘柄追加削除 |

## テスト

```bash
# stock-advisor（220 tests）
cd ~/.dotfiles/claude/skills/stock-advisor/scripts
.venv/bin/python -m pytest tests/ -q

# stock-company-analyze（88 tests）
cd ~/.dotfiles/claude/skills/stock-company-analyze
python3 -m pytest tests/ -q
```
