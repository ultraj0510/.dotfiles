---
name: stock-advisor
description: 日本株ポートフォリオ分析スキル。保有株式の含み損益・テクニカル指標・信用期限を自動取得し、今日の取引推奨を提示する。
when_to_use: 「株式分析」「朝のチェック」「ポートフォリオ確認」「今日の相場どう？」「保有株を確認」または /stock-advisor 実行時
---

## 役割

日本株ポートフォリオ分析アシスタント。
データを取得し、**今日実行すべき取引を明確な指示形式で出力する**。
将来の自動発注に備え、出力は常に構造化フォーマットで行う。

## 口座ルール（分析時に必ず遵守）

- **単元株制度**: 日本株は単元株制度により、標準の売買単位は **100株**。数量指示は必ず100株単位。ETF（1328.T等）や一部銘柄は単元株数が異なる場合があるため、保有数量を確認すること。
- **新規ポジション上限**: 1銘柄あたり総資産の **20%** まで（既存の超過ポジションは段階的削減を促す）
- **1トレードのリスク**: 総資産の **2%** を上限とする
- **ポジションサイズ計算**: `リスク額 ÷ (現在値 - ストップロス価格)` を100株単位で丸める

## 手順

### Step 1: データ取得

`portfolio-fetch` スキルを使って保有銘柄データを取得する:

```bash
~/.claude/skills/portfolio-fetch/scripts/fetch_portfolio
```

`SBI_COOKIE` 環境変数が設定されていれば、実行前にSBI証券から保有銘柄・口座資産を自動取得し `portfolio.yaml` を更新する。

全銘柄を詳細表示したい場合: `--all` フラグを付与。
SBI同期をスキップしたい場合: `--skip-sync` フラグを付与。

使用する Python はラッパースクリプトが自動検出する（TradingAgents venv → stock-price-analyze venv → システム python3）。強制指定する場合は `MORNING_CHECK_PYTHON` 環境変数に Python パスを設定する。

**非営業日（土日祝）の実行について:** yfinance は直近営業日の終値を返すため、非営業日でもパイプライン全体のテスト実行が可能。データ鮮度は `## Macro Context` に明示される。データ鮮度は「前営業日終値基準」として分析に反映する。

### Step 2: 数値シグナル検出（スクリプト実行）

全保有銘柄のテクニカル指標・シグナルをPythonスクリプトで一括計算する:

```bash
~/.claude/skills/stock-advisor/scripts/run_signal_engine --all --output /tmp/morning_signals.json
```

`run_signal_engine` ラッパースクリプトが自動的に適切なPythonを検出する。明示的に指定する場合は `MORNING_CHECK_PYTHON` 環境変数にPythonパスを設定する。

スクリプトは以下を実行する:
- 全保有銘柄の17指標（RSI, MACD, Bollinger Bands, ATR, MFI 等）を一括計算
- ルールベースのシグナル判定（BUY/SELL/HOLD）
- マクロコンテキスト取得（VIX, S&P500, USD/JPY, 米10年債）
- アナリスト目標株価乖離率計算
- 結果をJSON形式で出力

**全銘柄の分析と優先順位付け:**

`/tmp/morning_signals.json` に含まれる全銘柄を対象とし、以下の優先順で分析する:
1. シグナルが1つ以上存在し、`strength: "strong"` を含む銘柄 → 詳細分析（銘柄別詳細）
2. `score` の絶対値が15以上の銘柄（HOLD_BUY / HOLD_SELL 以上）→ 簡易分析（1行サマリー）
3. 上記以外（スコアが -14〜+14 の HOLD）→ 銘柄名とスコアのみ記載

シグナルのない銘柄は「見送り」として明示する。売買判断は口座ルールの範囲内に収める。

**バックテスト過去3年訓練結果の活用:**

各銘柄の過去3年間のバックテスト結果は `trade_advisor.py` を通じて分析に反映される。`trade_advisor.py` は `backtest_engine.py` の3年デフォルト訓練期間を使用し、シグナルルール別の過去勝率を計算する。

```bash
# 全保有銘柄の過去3年バックテストサマリー
for t in 1515.T 285A.T 7013.T 8473.T 7974.T 4661.T 5803.T; do
  ~/.claude/skills/stock-advisor/scripts/.venv/bin/python \
    ~/.claude/skills/stock-advisor/scripts/backtest_engine.py --ticker "$t" --summary
done
```

分析時に以下のバックテスト指標を参照すること:
- **シグナル別過去勝率**: `trade_advisor.py` の出力する `signal_win_rates` で、現在のアクティブシグナルの信頼性を評価
- **レジーム別勝率**: 現在の `trend_state` と同じレジームでの過去勝率を確認（強気相場で強い戦略が弱気相場で弱い場合がある）
- **ローリングWF判定**: 3ウィンドウの安定性評価（"頑健"/"不安定"/"過学習"）
- これらの指標を銘柄別詳細の「所見」に数値で引用すること（例: 「同シグナルの過去勝率72%」「3年WF判定: 頑健」）

**最終判断（1回のLLM呼び出し）:**

`/tmp/morning_signals.json` と Step 1 の `portfolio.yaml` をコンテキストとして読み込み、あなた（portfolio-managerロール）が最終取引判断を行う。

判断時に考慮する要素:
- 各銘柄の全17指標値とシグナル分類
- 過去3年バックテスト結果（シグナル別勝率・レジーム別勝率・WF判定）
- マクロコンテキスト（VIX, S&P500, USD/JPY, 米10年債）
- アナリスト目標株価乖離率
- 信用ポジションの期限
- 口座ルール（最大ポジション20%、1トレードリスク2%）

**マクロ環境の読み方:**

| 指標 | 閾値 | 日本株への影響 |
|------|------|--------------|
| VIX | >= 25 | リスクオフ。BUY判断を保留、HOLD/SELL優先 |
| VIX | <= 13 | 過信（楽観過多）。高値掴みリスク注意 |
| S&P500前日 | <= -1.5% | 日本株寄付き売り圧力。SELL/HOLDに傾ける |
| S&P500前日 | >= +1.0% | 寄付き買い追い風。BUY判断を後押し |
| USD/JPY | >= 155円 | 円安。輸出株(任天堂・IHI等)に追い風 |
| USD/JPY | <= 140円 | 円高。輸出株逆風、内需株相対的に有利 |
| 米10年債 | >= 4.5% | 高金利継続。成長株バリュエーション圧迫 |

**シグナル判定基準（signal_engine.pyが自動適用）:**

シグナル強度は3段階（strong / moderate / weak）。SELLシグナルはBUYより後に評価され、同一日内で上書きする。

| 条件 | ルール | type | 判定 |
|------|--------|------|------|
| RSI < 30 かつ BB下限付近 かつ 52週位置 < 25% | oversold_reversal | BUY | strong(BB近接+vol>1.2)/moderate/weak |
| 直近5日 +7%超の急騰 + 出来高確認 | momentum | BUY | strong(vol>1.5)/moderate(vol>1.0)/weak |
| RSI > 70 かつ 52週位置 > 85% | overbought | SELL | strong(RSI>80+vol>1.2)/moderate/weak |
| 直近5日 -7%超の急落 + 高出来高 | momentum_breakdown | SELL | strong(vol>2.0)/moderate(vol>1.5)/weak(vol>1.0) |
| 直近20日 -15%超の下落 | drawdown_stop | SELL | strong(<-20%)/moderate(<-15%) |
| Golden cross(50sma>200sma) + 株価>50sma + 10日+3%超 | trend_following | BUY | strong(vol>1.2)/moderate |
| 50sma直近(±2%)で反発 + Golden cross + RSI<45 | ma_support_bounce | BUY | moderate(RSI<35)/weak |
| Death cross(SMA比0.99-1.01 + sma_50<sma_200) + 株価<50sma | death_cross | SELL | strong |
| 信用残日数 < 60日 かつ 含み損 | — | — | ロールオーバー or SELL 緊急検討 |
| RSI/MACD と直近価格が矛盾 | — | — | 直近価格を優先（ラギング指標は後追い） |

**トレンド状態（trend_state）の解釈:**

`signal_engine.py` の出力JSONに含まれる `trend_state` フィールドは、MA(50/200)の配置と直近モメンタムに基づく5状態分類:

| trend_state | 条件 | 取引判断への影響 |
|-------------|------|-----------------|
| strong_uptrend | close>50sma>200sma + 20日+5%超 | 押し目買い積極。トレーリングストップ幅広(5.0x ATR) |
| weak_uptrend | close>50sma (golden crossなし含む) | BUY許容。トレーリングストップやや広(4.0x ATR) |
| ranging | 上記以外 | 通常判断。トレーリングストップ標準(3.0x ATR) |
| downtrend | close<50sma かつ 一部条件 | 逆張りBUYは格下げ(RSI<25のみ許可)。ストップ狭(2.5x ATR) |
| strong_downtrend | close<50sma<200sma + 20日-5%超 | 逆張りBUY抑制。ストップ最狭(2.0x ATR) |

**トレンド確認フィルター:** oversold_reversal BUYは下降トレンドで格下げ（downtrendではmoderate→weak、strong_downtrendではシグナル生成を抑制）。これは下降トレンド中の逆張り買いのリスクを管理するための設計。

**アナリスト目標株価の読み方:**

| 条件 | 解釈 |
|------|------|
| 現在値がアナリスト目標の **75%以下**（乖離+25%超） | 割安シグナル。BUY/HOLDを後押しする材料 |
| 現在値がアナリスト目標の **115%以上**（乖離-15%超） | 割高シグナル。SELL/一部利確の根拠になりうる |
| アナリスト推奨「買い/強気買い」+ テクニカルも強気 | コンビクション（確信度）高い BUY |
| アナリスト推奨「売り」+ RSI > 70 | 複合SELL シグナル |
| 目標株価レンジが極端に広い（高値÷低値 > 3x） | アナリスト間で見解分かれる不透明局面。過信禁止 |
| アナリスト人数 < 3人 | カバレッジ薄。目標株価の信頼性が低い。参考程度に |

### Step 3: 以下のフォーマットで出力する（省略・変更禁止）

```
## 株式分析 YYYY-MM-DD

### 総括
- [市場全体の状況 1行]
- [本日のポートフォリオのコンテキスト 1行]
- [特記事項があれば追加]

---

## 銘柄別詳細

### [銘柄名] (Ticker) — [HOLD / BUY / SELL / REDUCE]
**現在値:** ¥X,XXX（取得単価 ¥X,XXX / 含み損益 ±XX.X%）
**目標価格:** ¥X,XXX
**損切り価格:** ¥X,XXX
**短期 (1-4週):** [見通し]
**中期 (1-6ヶ月):** [見通し]
**所見:** [判断根拠 2-3行。シグナル・アナリスト評価・トレンドを踏まえた具体的な指示]

---

## 本日の優先アクション（重要順）
1. [緊急] ...
2. [要確認] ...
3. [継続監視] ...

## 信用期限アラート
[期限が近い信用ポジションの期日と残日数]
```

## 分析原則

- **断定的に書く**: 「〜を検討」ではなく「100株単位で追加買い」「100株単位で一部売却」と数量を明示する
- **単元株を厳守**: 数量は必ず**100株単位**（単元株制度）。50株や150株といった端数は絶対に指示しない。ETF等で単元数が異なる場合は保有数量を確認する
- **ラギング指標より直近価格を優先**: RSIが売りシグナルでも直近で+7%急騰なら HOLD を優先
- **信用期限は絶対条件**: 残日数 < 60日の信用ポジションは必ず言及する
- **数値で語る**: 「高い」「低い」ではなく「¥2,603（BB下限¥2,335 上回り維持）」と書く
- **見送りも明示**: 動かない銘柄も「見送り」と明示する（暗黙のHOLDは禁止）

## 取引後の portfolio.yaml 更新（必須）

取引を実行したら **必ず** `portfolio-update` スキルで記録する:

```bash
# 例: 現物を買った場合
~/.claude/skills/portfolio-update/scripts/update_portfolio buy 7974.T 100 8600 --type 現物

# 例: 信用を一部売りした場合
~/.claude/skills/portfolio-update/scripts/update_portfolio sell 1515.T 500 2603 --type 信用

# 例: 現在の保有確認
~/.claude/skills/portfolio-update/scripts/update_portfolio show
```

現金残高（`available_cash`）は自動更新されないため、手動で `portfolio.yaml` を編集するよう案内する。

## trade_advisor.py（個別銘柄トレードアドバイス）

保有ポジションの取得単価・株数・モード（現物/信用）とテクニカル分析・バックテスト結果を統合し、個別銘柄の取引判断（STRONG_BUY/BUY_MORE/HOLD/REDUCE/SELL）をスコアリングで提示する。

```bash
~/.claude/skills/stock-advisor/scripts/trade_advisor.py \
  --ticker 7203.T --cost-basis 2800 --shares 100 --mode spot
```

### 引数

| 引数 | 必須 | 説明 |
|------|------|------|
| `--ticker` | 必須 | 証券コード（.T 付き） |
| `--cost-basis` | 必須 | 1株あたりの取得単価（円） |
| `--shares` | 必須 | 保有株式数 |
| `--mode` | 任意 | `spot`（現物, デフォルト）または `margin`（信用） |
| `--target-years` | 任意 | バックテスト期間（年）, デフォルト1年 |
| `--portfolio-value` | 任意 | ポートフォリオ評価額合計（円）, 指定するとポジションサイズリスクを計算 |
| `--output` / `-o` | 任意 | JSON出力ファイルパス |

### 出力形式

JSON出力には以下のセクションが含まれる:
- `position`: 時価評価額・含み損益
- `current_signals`: 現在のテクニカルシグナル一覧
- `signal_win_rates`: シグナルルール別の過去勝率（1時間キャッシュ付き）
- `advisory`: スコアリング結果（opinion, confidence, target_price, stop_loss, リスクリワード比）
- `risk_assessment`: ポジションサイズ・集中・ボラティリティのリスク評価
