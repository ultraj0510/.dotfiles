---
name: stock-signals
description: シグナル判定・トレンド状態の解釈知識。signal_engineの出力を読み解くためのルール集。
---

# stock-signals — シグナル解釈

## シグナル判定基準 (signal_engine.py自動適用)

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

## トレンド状態 (trend_state)

signal_engine.py出力の `trend_state` はMA(50/200)の配置と直近モメンタムに基づく5状態分類:

| trend_state | 条件 | 取引判断への影響 |
|-------------|------|-----------------|
| strong_uptrend | close>50sma>200sma + 20日+5%超 | 押し目買い積極。トレーリングストップ幅広(5.0x ATR) |
| weak_uptrend | close>50sma (golden crossなし含む) | BUY許容。トレーリングストップやや広(4.0x ATR) |
| ranging | 上記以外 | 通常判断。トレーリングストップ標準(3.0x ATR) |
| downtrend | close<50sma かつ 一部条件 | 逆張りBUYは格下げ(RSI<25のみ許可)。ストップ狭(2.5x ATR) |
| strong_downtrend | close<50sma<200sma + 20日-5%超 | 逆張りBUY抑制。ストップ最狭(2.0x ATR) |

**トレンド確認フィルター**: oversold_reversal BUYは下降トレンドで格下げ（downtrend→weak、strong_downtrend→抑制）。

## 総合スコアリング

BUYシグナル: strong=+20, moderate=+10, weak=+5
SELLシグナル: strong=-25, moderate=-15, weak=-5
アナリスト乖離: >25%割安 → +10, >15%割高 → -10

| スコア | 推奨 |
|--------|------|
| >= 20 | STRONG_BUY |
| 15〜19 | HOLD_BUY |
| -14〜14 | HOLD |
| -15〜-19 | HOLD_SELL |
| <= -20 | SELL |

## 分析優先順位

1. シグナル1つ以上 + `strength: "strong"` → 詳細分析
2. `|score| >= 15` (HOLD_BUY / HOLD_SELL) → 簡易分析
3. 上記以外 → 銘柄名・スコアのみ
4. シグナルなし → 「見送り」明示
