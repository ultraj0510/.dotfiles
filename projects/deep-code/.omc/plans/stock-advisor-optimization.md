# Stock-Advisor Optimization Plan

## Status: pending approval (Final — Critic APPROVED v4 with minor reservations)

---

## RALPLAN-DR Summary

### Principles
1. **Script over LLM**: 定量化可能な指標計算・シグナル判定はPythonスクリプトで実行し、LLMは最終判断の1回のみにする
2. **Evidence-driven thresholds**: シグナル閾値は過去データのバックテスト結果に基づいて設定する
3. **Reuse before rewrite**: TradingAgentsの`dataflows/`層（純粋Python、LangChain非依存）の実戦テスト済みデータ取得・指標計算コードを抽出再利用する
4. **Structured output**: 中間データはJSON形式で構造化し、人間・LLM双方が解釈しやすくする
5. **Single source of truth**: シグナル判定ロジックは`signal_engine.py`に集約し、stock-advisor/stock-scan/stock-backtestの全スキルが同一コードを参照する

### Decision Drivers (Top 3)
1. **コスト削減**: LLM呼び出しを18回→1回に削減し、レイテンシとAPIコストを大幅に低減する
2. **検証可能性**: バックテストでシグナルルールの過去パフォーマンスを数値化し、閾値チューニングを可能にする
3. **移植性**: Mac (stock-price-analyze) と WSL (TradingAgents) 両環境で動作する単一のスクリプト基盤を作る

### Viable Options

#### Option A: 完全スタンドアロン — 全コードを新規作成
- `~/.claude/skills/stock-advisor/scripts/` に全Pythonコードを新規作成
- yfinance + stockstats + pandas のみに依存（TradingAgents非依存）
- **Pros**: 最小依存、シンプルな権限、プロジェクト移動に強い
- **Cons**: TradingAgentsの`dataflows/`層の実戦テスト済みコード（`load_ohlcv`, `yf_retry`, `_compute_custom_indicator`, `_get_stock_stats_bulk`）約200行を重複実装することになる。リトライ・キャッシュ・データクリーンアップロジックの再実装でバグ混入リスク

#### Option B: TradingAgentsをパッケージインストールしてデータフロー層をimport
- `pip install -e /home/ultraj/projects/TradingAgents` でパッケージ化
- `from tradingagents.dataflows.y_finance import load_ohlcv, _compute_custom_indicator` で再利用
- **Pros**: 既存コードを最大限再利用、コード重複ゼロ
- **Cons**: TradingAgentsはroot所有のため`pip install`が`.egg-info`/`__pycache__`書き込みで失敗する可能性。`pyproject.toml`の全依存（LangChain, backtrader等）がダウンロードされる（importはされないが、インストール時のオーバーヘッド）

#### Option C: ハイブリッド — TradingAgents dataflowsから必要関数を抽出コピー (RECOMMENDED)
- `load_ohlcv`, `yf_retry`, `_compute_custom_indicator`, `_get_stock_stats_bulk` をTradingAgentsから抽出
- `~/.claude/skills/stock-advisor/scripts/data_utils.py` として配置（出典コメント付き）
- キャッシュディレクトリを `~/.claude/skills/stock-advisor/scripts/cache/` に移動
- 新規に書くのはシグナル判定ロジックとバックテストエンジンのみ
- **Pros**: データ取得・指標計算の信頼性高いコードを再利用。root権限制約を回避。yfinance+stockstats+pandasのみの依存。TradingAgents更新と抽出コード間のドリフトは最小限（dataflows層は安定している）
- **Cons**: 約60行のコード抽出・adaptationが必要。出典帰属のコメント管理が必要

### Pre-mortem (Failure Scenarios)
1. **データ取得の信頼性**: yfinanceのAPI制限や仕様変更でデータ取得に失敗 → キャッシュ層とリトライ機構で緩和。yfinanceの`auto_adjust`パラメータが非推奨化された場合、`load_ohlcv`内の当該行を修正する必要がある
2. **シグナル過剰反応**: ルールベース化でノイズに過剰反応し、不必要な売買シグナルが増加 → バックテストで確認しながら閾値調整
3. **環境間の差異**: Mac/WSLでPythonバージョンやパッケージバージョンの差異 → requirements.txtでバージョン固定
4. **CSVキャッシュ破損**: キャッシュファイルの部分書き込みやディスクフルで不正データがバックテスト結果に混入 → キャッシュ読み込み時のバリデーション（行数チェック、日付範囲チェック）を追加
5. **Walk-forward分析のregime過適合**: トレンド相場でチューニングした閾値がレンジ相場で機能しない → 複数銘柄でのクロスバリデーション。train期間とtest期間のパフォーマンス差が20%を超えた場合は閾値チューニングを破棄しデフォルト値を使用
6. **全銘柄シグナル不在**: 保有全銘柄にシグナルが一つも出ない日 → 「見送り」として正常終了。異常検知ロジックで市場全体のデータ取得失敗と区別する
7. **抽出コードとTradingAgents原本のドリフト**: TradingAgentsのdataflows層が更新され、抽出コードと乖離 → dataflows層は安定しており更新頻度は低い。抽出コードには出典行番号をコメントし、半年ごとのdiff確認をfollow-upに追加

---

## Implementation Steps

### Phase 0: 前提条件セットアップ

#### Step 0: Python venv環境の構築
- **yfinance, stockstats はWSL上のどのPython環境にも未インストール**
- `~/.claude/skills/stock-advisor/scripts/.venv/` に専用venvを作成
- `portfolio-fetch/scripts/fetch_portfolio` のPython検出パターンをテンプレートとして再利用
- ラッパースクリプト `run_signal_engine` を作成し、venvのPythonを自動検出
- 検出順序: `$MORNING_CHECK_PYTHON`（既存のportfolio-fetchと同じ命名規則）→ `stock-advisor/scripts/.venv/bin/python` → TradingAgents venv → システムpython3

### Phase 1: Signal Engine (数値化・スクリプト化)

#### Step 1: TradingAgents dataflowsからデータ取得・指標計算コードを抽出
- **抽出元**: `/home/ultraj/projects/TradingAgents/tradingagents/dataflows/`
- **抽出先**: `~/.claude/skills/stock-advisor/scripts/data_utils.py`
- **抽出対象** (全5関数 + 1グローバル変数):
  - `yf_retry()` (`stockstats_utils.py:15-31`) — 指数バックオフ付きyfinanceリトライ
  - `_clean_dataframe()` (`stockstats_utils.py:34-44`) — OHLCVデータのクリーニング（NaN除去、列名正規化）
    - **抽出必須**: `load_ohlcv()` が `stockstats_utils.py:83` で内部呼び出しするため
  - `load_ohlcv()` (`stockstats_utils.py:47-88`) — OHLCVデータ取得 + CSVキャッシュ
    - **要修正**: `config.get_config()` 呼び出し（`stockstats_utils.py:54`）は `tradingagents.default_config` に依存しているため、モジュール定数 `CACHE_DIR = os.path.expanduser("~/.claude/skills/stock-advisor/scripts/cache/")` に置き換える
    - **要修正**: CSVキャッシュ書き込み時に `tempfile.NamedTemporaryFile` + `shutil.move` によるアトミック書き込みに変更し、同時書き込み破損を防止（pre-mortem #4対策）
  - `_CUSTOM_INDICATORS` グローバルセット (`y_finance.py:10`) — `_get_stock_stats_bulk()` が参照するため抽出必須
  - `_compute_custom_indicator()` (`y_finance.py:212-231`) — 5d/20dリターン、52週位置、出来高比率
  - `_get_stock_stats_bulk()` (`y_finance.py:234-274`) — stockstatsで17指標一括計算
    - **注意**: `_CUSTOM_INDICATORS` グローバルを参照するためセットで抽出すること
- キャッシュディレクトリを `~/.claude/skills/stock-advisor/scripts/cache/` に変更
- 出典コメントを明記（ファイルパス、行番号）
- yfinanceの `auto_adjust=True` は株価を配当・株式分割調整済みで返す。バックテストPnL計算では価格リターンのみを扱い、配当収入は含まれないことをコメントで明記

#### Step 2: `signal_engine.py` の作成
- **場所**: `~/.claude/skills/stock-advisor/scripts/signal_engine.py`
- **機能**:
  - `data_utils.py` からデータ取得・指標計算関数をimport
  - シグナル判定ルール（stock-advisor SKILL.mdの表をPythonにエンコード）:
    - RSI < 30 + BB下限付近 + 52週位置 < 25% → BUYシグナル
    - RSI > 70 + 52週位置 > 85% → SELLシグナル
    - 5日間+7%超の急騰 + 出来高確認 → モメンタムBUY
    - 信用残日数 < 60日 + 含み損 → 緊急SELL
  - マクロコンテキスト判定:
    - VIX (`^VIX`), S&P500 (`^GSPC`), USD/JPY (`JPY=X`), 米10年債 (`^TNX`) をyfinanceで取得
    - 日経先物はyfinanceで信頼性が低いため初版ではスキップ（フォローアップで追加）
  - アナリスト目標株価判定（乖離率計算）
  - 空売り残高判定
  - **出力**: JSON形式（全指標値 + シグナル分類 + スコア）
- **依存**: yfinance, stockstats, pandas, numpy

#### Step 3: `backtest_engine.py` の作成
- **場所**: `~/.claude/skills/stock-advisor/scripts/backtest_engine.py`
- **機能**:
  - 指定銘柄・期間（デフォルト1年）の日次データを `data_utils.load_ohlcv()` で取得
  - 各営業日で `signal_engine` の判定ロジックを適用
  - シグナルに基づく仮想取引シミュレーション:
    - ポジションサイズ計算（総資産2%ルール）
    - ストップロス執行
    - 手数料考慮（0.1%想定）
  - パフォーマンス指標算出:
    - 総リターン、CAGR
    - Sharpe ratio, Sortino ratio
    - Max drawdown
    - Win rate, Profit factor
    - トレード回数、平均保有日数
  - パラメータグリッドサーチ（閾値チューニング用）:
    - **Walk-forward分析**: 最初の70%期間でグリッドサーチ、最後の30%で検証
    - **チューニング対象を4パラメータに限定**: RSI下限閾値（デフォルト30, 範囲25-40）、RSI上限閾値（デフォルト70, 範囲65-80）、52週位置下限（デフォルト25%, 範囲15-35%）、52週位置上限（デフォルト85%, 範囲75-95%）
    - **過剰適合ガード**: train期間とtest期間のSharpe ratio差が50%超またはtest期間のSharpe ratioが負の場合、チューニング結果を破棄しデフォルト閾値を使用
    - BB位置はパラメータとしてチューニングしない（過剰適合防止）
    - 初期は単一70/30ウィンドウで実装。複数銘柄でのクロスバリデーションによりregime依存性を評価。複数ローリングウィンドウはfollow-upで追加
  - **出力**: JSON形式（指標一覧 + トレード履歴 + グリッドサーチ結果）

#### Step 4: `requirements.txt` の作成とインストール
- **場所**: `~/.claude/skills/stock-advisor/scripts/requirements.txt`
- **内容**: yfinance, stockstats, pandas, numpy, jpholiday のバージョン固定（jpholidayは日本株の営業日判定に使用）
- **インストール手順**: `cd ~/.claude/skills/stock-advisor/scripts && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- **検証**: `.venv/bin/python -c "import yfinance; import stockstats; import pandas; print('OK')"` で確認

### Phase 2: Skillファイルの修正

#### Step 5: `stock-advisor/SKILL.md` の修正
- Step 2 の「要アクション銘柄の多段階エージェント分析」を削除
- 代わりに `signal_engine.py` の実行手順を追加:
  ```bash
  python3 ~/.claude/skills/stock-advisor/scripts/signal_engine.py --ticker {TICKER}
  ```
- 全銘柄のシグナルJSONを収集後、上位3銘柄をルールベースで選定
- 最終判断は1回のLLM呼び出しで実行（portfolio-managerロール、シグナルJSONをコンテキストとして渡す）
- Step 3 の出力フォーマットは維持

#### Step 6: `stock-backtest/SKILL.md` の修正
- `stock-price-analyze/main.py backtest` 呼び出しを `backtest_engine.py` 呼び出しに置き換え
- チューニング用の `--tune` オプション追加
- `backtest_engine.py` は `stock-advisor/scripts/` に配置し、stock-backtestからはパス指定で呼び出し

#### Step 7: `stock-scan/SKILL.md` の修正
- `stock-price-analyze/main.py scan` 呼び出しを `signal_engine.py --all` に置き換え

#### Step 8: `portfolio-fetch` との連携確認
- 既存の `fetch_portfolio` の出力形式を確認
- `signal_engine.py` がportfolio-fetchの出力（保有銘柄リスト）を入力として受け取れるようCLI引数設計:
  - `--ticker <TICKER>`: 単一銘柄のシグナル計算
  - `--tickers <TICKER1,TICKER2,...>`: 複数銘柄を一括処理
  - `--all`: デフォルトの銘柄リストを処理
    - WSLでは `~/.claude/skills/stock-advisor/scripts/default_tickers.txt`（1行1ticker）から読み込み
    - **初期化**: `echo "1515.T" > ~/.claude/skills/stock-advisor/scripts/default_tickers.txt` でseedファイルを作成（ユーザーが保有銘柄に応じて編集）
    - Macでは既存の `portfolio.yaml` を利用可能
- **注意**: `fetch_portfolio` は `stock-price-analyze`（Mac専用、WSLに不在）に依存している。この依存は本計画の範囲外だが、将来的に `data_utils.py` を使ってWSLでも完結するよう改修可能
- **休日/非営業日の処理**: `signal_engine.py` は `data_utils.load_ohlcv()` が返す直近営業日のデータを使用。日本株の場合は `jpholiday` ライブラリ（TradingAgentsで既使用）で営業日判定

### Phase 3: バックテスト実行と閾値チューニング

#### Step 9: 保有銘柄のバックテスト実行
- 全保有銘柄に対し、デフォルト閾値で1年間バックテスト実行
- 各銘柄のパフォーマンス指標を比較

#### Step 10: 閾値パラメータのグリッドサーチ
- 主要閾値（RSI閾値、BB位置、52週位置等）のグリッドサーチ実行
- 最適パラメータを特定し、signal_engine.pyのデフォルト値を更新

## Acceptance Criteria

1. `signal_engine.py` が全17指標を数値計算し、シグナル判定結果をJSONで出力できる
2. `backtest_engine.py` が1年分の日次データでバックテストを実行し、Sharpe ratio, max drawdown, win rate等を算出できる
3. `stock-advisor/SKILL.md` のStep 2からマルチエージェントパイプラインが削除され、スクリプト呼び出しに置き換わっている
4. モーニングチェックのLLM呼び出し回数が18回→1回（portfolio-manager最終判断のみ）に削減されている
5. バックテスト結果に基づく閾値チューニングがwalk-forward分析（70/30分割）で完了し、デフォルト閾値が更新されている
6. `signal_engine.py` の判定と既存の6エージェントLLM分析による判定（`_workspace/*/06_final_decision.md`）の方向性一致率が70%以上であること。方向性の分類は3値（BUY / HOLD / SELL）で照合し、PARTIAL_SELLはSELLとして扱う。70%未満の場合は、全不一致ケースの比較表を出力し、スクリプト判定が明確に誤っていないことを確認してから進行する
7. WSL環境の専用venvで全スクリプトが動作する（yfinance, stockstats, pandasが利用可能）
8. スクリプトがPython 3.10+の標準macOS環境で `pip install -r requirements.txt` 後に動作すること。ユーザーによるMac上での実行確認を以て検証完了とする

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| yfinance API制限/仕様変更 | データ取得不能 | キャッシュ層で前回取得成功データを再利用。キャッシュも不在の場合はエラー終了し、LLMベースの旧パイプラインにフォールバック可能 |
| スクリプト化で判断の柔軟性が低下 | 異常相場で誤シグナル | 最終判断にLLMを1回残す、異常検知ルール追加 |
| バックテストのoverfitting | 実運用で性能劣化 | Walk-forward分析（70% train / 30% test）、チューニングパラメータを3-4個に制限 |
| 日経先物データ不在 | ギャップアップ/ダウン検知不可 | 初版では日経先物判定をスキップ、フォローアップで追加 |
| Mac/WSL間の環境差異 | 一方の環境でのみ動作不能 | requirements.txtでバージョン固定、portfolio-fetchのPython検出パターン再利用 |

## Verification Steps

1. `signal_engine.py` を既存取引候補銘柄（1515.T, 7974.T, 7013.T）で実行し、出力JSONの指標値・シグナル判定の妥当性を確認
2. `backtest_engine.py` を1515.Tで1年間実行し、生成されるパフォーマンス指標が計算的に正しいか検証
3. 修正後のstock-advisor SKILL.mdでモーニングチェックを実行し、Step 3の出力フォーマット（取引指示一覧・銘柄別詳細）が維持されているか確認
4. `signal_engine.py` の判定結果と `_workspace/*/06_final_decision.md` のFINAL_DECISIONを比較し、方向性の一致率を確認（70%以上を目標。未達の場合は不一致ケースの比較表を出力し、スクリプト判定が明確に誤っていないか検証）
5. `backtest_engine.py` のwalk-forward分析でtrain期間とtest期間のSharpe ratio差が50%以内であること、かつtest期間のSharpe ratioが正であることを確認（違反時はデフォルト閾値を使用）
6. WSL環境で `requirements.txt` からvenvを作成し、全スクリプトが正常実行できることを確認
7. Mac環境で `pip install -r requirements.txt` 後に全スクリプトが動作するか確認（ユーザーに依頼）

---

## Test Plan (Deliberate Mode)

### Unit Tests
- `data_utils.py`: `_compute_custom_indicator()` に既知のOHLCVデータを入力し、5d/20dリターン・52週位置・出来高比率が手計算と一致することを確認
- `signal_engine.py`: 各シグナル判定ルール（RSI < 30 + BB下限、RSI > 70 + 52週位置 > 85%等）に境界値を入力し、期待されるシグナルが出力されることを確認
- `backtest_engine.py`: 既知の価格系列とシグナル系列でポジションサイズ計算・ストップロス・手数料が正しいことを確認

### Integration Tests
- `data_utils.load_ohlcv()` → `_get_stock_stats_bulk()` のパイプラインを1515.Tで実行し、全17指標が欠損なく出力されることを確認
- `signal_engine.py` が `data_utils.py` の全関数を呼び出し、JSON出力が有効な形式であることを確認
- `backtest_engine.py` が `signal_engine` の判定ロジックを再利用し、一貫した結果を生成することを確認

### E2E Tests
- 修正後のstock-advisor SKILL.mdのStep 1〜3を通しで実行し、取引指示一覧・銘柄別詳細が完全なフォーマットで出力されることを確認
- stock-scan SKILL.mdから `signal_engine.py --all` を実行し、全銘柄のシグナル一覧が出力されることを確認

### Observability
- `signal_engine.py` の実行ごとにタイムスタンプ・ticker・シグナル判定・エラー有無をログファイル（`~/.claude/skills/stock-advisor/scripts/logs/signal_log.jsonl`）に追記
- バックテスト実行時にパラメータ・日付範囲・結果サマリを同様にログ出力
- これによりシグナル精度の事後分析と閾値の継続的改善が可能

---

## ADR

### Decision
Option C (Hybrid): TradingAgentsの`dataflows/`層（純粋Python、LangChain非依存）から実戦テスト済みのデータ取得・指標計算コード（`load_ohlcv`, `yf_retry`, `_compute_custom_indicator`, `_get_stock_stats_bulk`）を抽出し、stock-advisorスキルに配置。シグナル判定ロジックとバックテストエンジンは新規作成。stock-advisorのマルチエージェントLLMパイプライン（18回のLLM呼び出し）をスクリプトベースの数値計算 + 1回の最終判断LLM呼び出しに置き換える。

### Drivers
- コスト削減（LLM呼び出し18回→1回）
- レイテンシ改善（エージェント逐次実行→スクリプト一括計算）
- 検証可能性の確保（バックテストによる閾値のエビデンスベース最適化）
- コード品質（実戦テスト済みのデータ取得ロジックを再利用し、バグ混入リスクを低減）

### Alternatives Considered
- **Option A (完全スタンドアロン)**: TradingAgentsのデータフロー層コード（約200行）を重複実装することになり、リトライ・キャッシュ・クリーンアップロジックの再実装でバグ混入リスク。コード重複は保守負荷という実質的な依存であるため不採用。
- **Option B (TradingAgentsパッケージインストール)**: root所有のTradingAgentsに`pip install -e .`する際の権限問題。また全依存（LangChain, backtrader等）のダウンロードが発生し、「シンプル化」目標に反するため不採用。
- **LLM完全排除**: 最終判断における市場コンテキストの総合的判断はLLMに優位性があるため、1回のLLM呼び出しは保持。

### Why Chosen
TradingAgentsの`dataflows/`層は純粋なPython（yfinance + stockstats + pandas）であり、LangChain/LangGraphに依存していない。この層のコードは既に実戦でテストされており、1515.Tのキャッシュ済みCSVが存在することがその証拠。抽出により約200行の新規バグ混入リスクを回避しつつ、root権限制約やTradingAgents全体の依存インストールを回避できる。

### Consequences
- 新規Python venv + 依存（yfinance, stockstats, pandas）のインストールが必要（WSL、Mac両方）
- 抽出コードとTradingAgents原本の間のドリフトは最小限（dataflows層は安定している）
- LLMの柔軟な判断が一部失われる（数値化できない定性情報の扱い）
- 日経先物データは初版では利用不可（yfinanceで信頼性低）

### Follow-ups
- バックテスト結果に基づくシグナル閾値の継続的チューニング
- 実運用パフォーマンスのトラッキングと閾値の再調整
- 日経先物データソースの調査と追加
- 異常相場検知ロジックの追加（VIX急騰時など）
- 複数ローリングwalk-forwardウィンドウによるregime横断的検証
- 抽出コードとTradingAgents原本の半年ごとdiff確認
- `fetch_portfolio` のstock-price-analyze依存を `data_utils.py` で置き換え、WSL完結型に改修
