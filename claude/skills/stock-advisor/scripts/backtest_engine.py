#!/usr/bin/env python3
"""Walk-forward backtest engine for rule-based stock trading signals.

Usage:
    python backtest_engine.py --ticker 1515.T
    python backtest_engine.py --ticker 1515.T --tune
    python backtest_engine.py --ticker 1515.T --start 2024-01-01 --end 2025-01-01

Limitations:
- Trailing stop uses closing prices only. Intraday gap-downs that recover
  by close are not captured as stop-loss events.
- ATR requires a 14-period warm-up; the first ~14 rows of the backtest
  period will have NaN ATR and the trailing stop will not fire.
"""

import argparse
import json
import math
import os
from datetime import timedelta

import numpy as np
import pandas as pd

from data_utils import _CUSTOM_INDICATORS, _get_stock_stats_bulk, load_ohlcv, safe_float
from signal_engine import compute_trend_state, get_latest_trading_day
from backtest_cache import load_cached_result, save_cached_result
from signal_rules import (
    RSI_LOWER, RSI_UPPER,
    POSITION_52W_LOWER, POSITION_52W_UPPER,
    MOMENTUM_5D, BREAKDOWN_5D, BREAKDOWN_VOL, DRAWDOWN_20D,
)

# Default signal thresholds (grid_search-compatible dict)
DEFAULT_THRESHOLDS = {
    "rsi_lower": RSI_LOWER,
    "rsi_upper": RSI_UPPER,
    "position_52w_lower": POSITION_52W_LOWER,
    "position_52w_upper": POSITION_52W_UPPER,
    "momentum_5d": MOMENTUM_5D,
    "breakdown_5d": BREAKDOWN_5D,
    "breakdown_vol": BREAKDOWN_VOL,
    "drawdown_20d": DRAWDOWN_20D,
}

DEFAULT_RISK_PARAMS = {
    "trailing_stop_atr_mult": {
        "strong_uptrend": 5.0,
        "weak_uptrend": 4.0,
        "ranging": 3.0,
        "downtrend": 2.5,
        "strong_downtrend": 2.0,
        "unknown": 3.0,
    },
    "atr_slew_max": 0.5,
    "vol_target": 0.15,         # 15% annualized target volatility
    "vol_target_min": 0.5,      # min position size multiplier
    "vol_target_max": 2.0,      # max position size multiplier
    "vol_lookback": 20,         # lookback days for realized vol
}

DEFAULT_MARGIN_PARAMS = {
    "margin_long_rate": 0.028,
    "margin_short_rate": 0.012,
    "margin_max_days": 180,
}

# Transaction cost model (A5)
# Tickers known to be TOPIX 500 constituents (lower slippage/impact)
TOPIX500_TICKERS = {
    # Automobiles & Transport
    "7203.T", "7267.T", "7201.T", "7202.T", "7269.T", "7270.T",
    # Electronics & Precision
    "6758.T", "7751.T", "7752.T", "7735.T", "6954.T", "6861.T", "8035.T",
    "6723.T", "6724.T", "6971.T", "6501.T", "6502.T", "6503.T", "6504.T",
    # Financials (Banks, Securities, Insurance)
    "8306.T", "8411.T", "8316.T", "8308.T", "8309.T", "7186.T", "7182.T",
    "8604.T", "8601.T", "8766.T", "8725.T", "8729.T", "8630.T", "8750.T",
    # Trading Companies & Industrials
    "8058.T", "8001.T", "8002.T", "8031.T", "8015.T",
    "7011.T", "7013.T", "7012.T", "6301.T", "6302.T", "6305.T", "6326.T",
    "5803.T", "5802.T", "5801.T",
    # Chemicals & Materials
    "4063.T", "4188.T", "3407.T", "3402.T", "4183.T",
    "5401.T", "5411.T", "5713.T",
    # Pharma & Healthcare
    "4502.T", "4503.T", "4519.T", "4568.T", "4523.T", "4151.T",
    # IT & Telecom
    "9984.T", "9432.T", "9433.T", "9434.T", "9613.T", "4689.T",
    "4307.T", "7974.T",
    # Consumer & Retail
    "2914.T", "3382.T", "8267.T", "4452.T", "4901.T", "4911.T",
    "7003.T", "7004.T", "9201.T", "9202.T",
    # Real Estate & Construction
    "8801.T", "8802.T", "8830.T", "1801.T", "1802.T", "1925.T",
    # Energy & Utilities
    "9501.T", "9502.T", "9503.T", "9531.T", "5020.T",
}

DEFAULT_COST_PARAMS = {
    "commission": 0.001,       # 0.1% per trade
    "slippage_topix500": 0.0005,   # 0.05% for TOPIX 500
    "slippage_other": 0.0015,      # 0.15% for others
    "impact_mult_topix500": 0.0015,  # 0.15% impact multiplier
    "impact_mult_other": 0.003,      # 0.30% impact multiplier
    "impact_cap": 0.02,              # 2.0% max impact
    "volume_floor": 1000,            # Floor for volume/avg_volume in impact calc
}


def _compute_transaction_cost(price: float, shares: int, ticker: str,
                               volume_ratio: float = 1.0,
                               cost_params: dict = None) -> dict:
    """Compute per-trade transaction costs in yen.

    Returns dict with commission, slippage, impact, total (all in yen).
    """
    if cost_params is None:
        cost_params = DEFAULT_COST_PARAMS

    notional = price * shares
    is_topix500 = ticker in TOPIX500_TICKERS

    # Commission and slippage apply to both entry and exit (round-trip)
    commission = notional * cost_params["commission"] * 2
    slippage = notional * (cost_params["slippage_topix500"] if is_topix500
                           else cost_params["slippage_other"]) * 2

    # Market impact: sqrt(volume_ratio) * impact_mult, capped at 2%
    # volume_ratio = volume / 20d_avg_volume, computed by data_utils
    safe_ratio = max(abs(volume_ratio) if volume_ratio and volume_ratio > 0 else 1.0, 0.1)
    impact_mult = (cost_params["impact_mult_topix500"] if is_topix500
                   else cost_params["impact_mult_other"])
    impact = min(
        math.sqrt(safe_ratio) * impact_mult * notional,
        cost_params["impact_cap"] * notional,
    )

    total = commission + slippage + impact

    return {
        "commission": round(commission, 2),
        "slippage": round(slippage, 2),
        "impact": round(impact, 2),
        "total": round(total, 2),
        "total_pct": round(total / notional * 100, 4) if notional > 0 else 0.0,
    }

# Grid search parameter ranges
TUNE_PARAM_GRID = {
    "rsi_lower": [20, 25, 30, 35],
    "rsi_upper": [65, 70, 75, 80],
    "position_52w_lower": [15, 20, 25, 30],
    "position_52w_upper": [80, 85, 90, 95],
}

ALL_INDICATORS = [
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh",
    "rsi",
    "boll", "boll_ub", "boll_lb",
    "atr", "vwma", "mfi",
] + sorted(_CUSTOM_INDICATORS)



# Strategy mode rule sets
STRATEGY_ALLOWED_RULES = {
    "trend": {
        "buy": {"trend_following", "momentum", "ma_support_bounce"},
        "sell": {"death_cross"},
    },
    "contrarian": {
        "buy": {"oversold_reversal"},
        "sell": {"overbought", "momentum_breakdown", "drawdown_stop"},
    },
}


def _is_rule_allowed(rule: str, signal_type: int, strategy_mode: str) -> bool:
    """Check whether a signal rule is allowed under the given strategy_mode.

    signal_type: 1=buy, -1=sell.
    """
    if strategy_mode == "default":
        return True
    mode_rules = STRATEGY_ALLOWED_RULES.get(strategy_mode)
    if mode_rules is None:
        return True
    key = "buy" if signal_type == 1 else "sell"
    return rule in mode_rules[key]


def _apply_rule_gate(signal_val, rule, strength, signal_type, strategy_mode):
    """Apply strategy mode gate: if rule is not allowed, clear signal/rule/strength."""
    if signal_val != 0 and rule and not _is_rule_allowed(rule, signal_type, strategy_mode):
        return 0, None, None
    return signal_val, rule, strength


def generate_signals(ticker: str, start_date: str, end_date: str,
                     thresholds: dict = None,
                     strategy_mode: str = "default") -> pd.DataFrame:
    """Generate buy/sell signals for each trading day in the date range.

    Returns DataFrame with columns: date, close, high, low, rsi, 52w_position,
    5d_return, volume_ratio, boll_lb, ret_20d, atr, trend_state, sma_50,
    sma_200, ret_10d, signal (1=buy, -1=sell, 0=hold).

    strategy_mode: "default" (all rules), "trend" (trend-following only),
                   "contrarian" (reversal-only).
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    # Build indicator DataFrame from bulk data
    indicator_data = {}
    for ind in ALL_INDICATORS:
        bulk = _get_stock_stats_bulk(ticker, ind, end_date)
        indicator_data[ind] = bulk

    # Get OHLCV data
    ohlcv = load_ohlcv(ticker, end_date)
    ohlcv["date_str"] = ohlcv["Date"].dt.strftime("%Y-%m-%d")
    close_map = dict(zip(ohlcv["date_str"], ohlcv["Close"]))
    high_map = dict(zip(ohlcv["date_str"], ohlcv["High"]))
    low_map = dict(zip(ohlcv["date_str"], ohlcv["Low"]))

    # Get all dates from any indicator
    all_dates = set()
    for ind_data in indicator_data.values():
        all_dates.update(ind_data.keys())
    dates = sorted(all_dates)

    # Filter to range
    dates = [d for d in dates if start_date <= d <= end_date]

    # Signal evaluation: 2-pass architecture.
    # Pass 1 — BUY rules (first-match-wins):
    #   oversold_reversal → momentum → trend_following → ma_support_bounce
    # Pass 2 — SELL rules (first-match-wins):
    #   overbought → momentum_breakdown → drawdown_stop → death_cross
    # If any SELL rule fires, it overwrites the BUY signal for that day.

    rows = []
    for d in dates:
        rsi = safe_float(indicator_data["rsi"].get(d))
        pos_52w = safe_float(indicator_data["52w_position"].get(d))
        ret_5d = safe_float(indicator_data["5d_return"].get(d))
        vol_ratio = safe_float(indicator_data["volume_ratio"].get(d))
        ret_20d = safe_float(indicator_data["20d_return"].get(d))
        atr = safe_float(indicator_data["atr"].get(d))
        sma_50 = safe_float(indicator_data["close_50_sma"].get(d))
        sma_200 = safe_float(indicator_data["close_200_sma"].get(d))
        ret_10d = safe_float(indicator_data["10d_return"].get(d))
        close_val = close_map.get(d, 0)
        if isinstance(close_val, pd.Series):
            close_val = float(close_val.iloc[0]) if not close_val.empty else 0
        else:
            close_val = float(close_val) if close_val else 0
        high_val = safe_float(high_map.get(d))
        if high_val is None:
            high_val = 0
        low_val = safe_float(low_map.get(d))
        if low_val is None:
            low_val = 0
        boll_lb = safe_float(indicator_data["boll_lb"].get(d))

        # Compute trend state for filter and adaptive logic
        trend_state = compute_trend_state({
            "close": close_val, "close_50_sma": sma_50,
            "close_200_sma": sma_200, "20d_return": ret_20d,
        }) if close_val and sma_50 and sma_200 else "unknown"

        signal = 0
        signal_rule = None
        signal_strength = None

        # Oversold reversal BUY (with trend filter)

        # Ensemble signal: evaluate all rules, sum contributions.
        # BUY rules add positive score, SELL rules add negative.
        # Final signal fires when total crosses threshold.
        STRENGTH_WEIGHT = {"strong": 2.0, "moderate": 1.0, "weak": 0.5}
        contributions = []  # (rule, direction, strength, score)

        # IC-based rule filter: exclude rules with weak recent predictive power
        ic_filter = {}
        try:
            if len(rows) >= 60:
                recent = pd.DataFrame(rows[-60:])
                closes = recent.get("close")
                if closes is not None and len(closes) > 10:
                    closes = closes.values
                    hdays = 5
                    if len(closes) > hdays:
                        fwd = np.zeros(len(closes))
                        fwd[:-hdays] = (closes[hdays:] - closes[:-hdays]) / closes[:-hdays]
                        rule_sigs = {}
                        for i, row in enumerate(rows[-60:]):
                            r = row.get("signal_rule")
                            s = row.get("signal", 0)
                            if r and s != 0 and i < len(fwd):
                                rule_sigs.setdefault(r, {"s": [], "f": []})
                                rule_sigs[r]["s"].append(s)
                                rule_sigs[r]["f"].append(fwd[i])
                        for rn, rd in rule_sigs.items():
                            if len(rd["s"]) >= 5:
                                ic_val = np.corrcoef(rd["s"], rd["f"])[0, 1]
                                ic_filter[rn] = abs(ic_val) >= 0.05
        except Exception:
            pass  # IC filter unavailable — use all rules

        # --- BUY rules ---
        # Oversold reversal
        if (rsi is not None and rsi < thresholds["rsi_lower"]
                and pos_52w is not None and pos_52w < thresholds["position_52w_lower"]
                and trend_state != "strong_downtrend"):
            vol_r = safe_float(vol_ratio) if vol_ratio else None
            if boll_lb and close_val and close_val <= boll_lb * 1.02 and vol_r and vol_r > 1.2:
                st = "strong"
            elif boll_lb and close_val and close_val <= boll_lb * 1.05:
                st = "moderate"
            else:
                st = "weak"
            if _is_rule_allowed("oversold_reversal", 1, strategy_mode) and ic_filter.get("oversold_reversal", True):
                contributions.append(("oversold_reversal", 1, st, STRENGTH_WEIGHT[st]))

        # Momentum BUY
        if ret_5d is not None and ret_5d > thresholds["momentum_5d"]:
            if vol_ratio and safe_float(vol_ratio) > 1.5:
                st = "strong"
            elif vol_ratio and safe_float(vol_ratio) > 1.0:
                st = "moderate"
            else:
                st = "weak"
            if _is_rule_allowed("momentum", 1, strategy_mode) and ic_filter.get("momentum", True):
                contributions.append(("momentum", 1, st, STRENGTH_WEIGHT[st]))

        # Trend following BUY
        if (sma_50 and sma_200 and sma_50 > sma_200
                and close_val and close_val > sma_50
                and ret_10d is not None and ret_10d > 3
                and vol_ratio and safe_float(vol_ratio) > 0.8):
            st = "strong" if (vol_ratio and safe_float(vol_ratio) > 1.2) else "moderate"
            if _is_rule_allowed("trend_following", 1, strategy_mode) and ic_filter.get("trend_following", True):
                contributions.append(("trend_following", 1, st, STRENGTH_WEIGHT[st]))

        # MA support bounce BUY
        if (sma_50 and sma_200 and sma_50 > sma_200
                and close_val and sma_50 * 0.98 <= close_val <= sma_50 * 1.02
                and rsi is not None and rsi < 45):
            st = "moderate" if (rsi and rsi < 35) else "weak"
            if _is_rule_allowed("ma_support_bounce", 1, strategy_mode) and ic_filter.get("ma_support_bounce", True):
                contributions.append(("ma_support_bounce", 1, st, STRENGTH_WEIGHT[st]))

        # --- SELL rules ---
        # Overbought SELL
        if (rsi is not None and rsi > thresholds["rsi_upper"]
                and pos_52w is not None and pos_52w > thresholds["position_52w_upper"]):
            st = "strong" if (rsi and rsi > 80 and vol_ratio and safe_float(vol_ratio) > 1.2) else "moderate"
            if _is_rule_allowed("overbought", -1, strategy_mode) and ic_filter.get("overbought", True):
                contributions.append(("overbought", -1, st, -STRENGTH_WEIGHT[st]))

        # Momentum breakdown SELL
        if (ret_5d is not None and ret_5d < thresholds["breakdown_5d"]
                and vol_ratio and safe_float(vol_ratio) > thresholds["breakdown_vol"]):
            vr = safe_float(vol_ratio) if vol_ratio else 1.0
            if vr > 2.0: st = "strong"
            elif vr > 1.5: st = "moderate"
            else: st = "weak"
            if _is_rule_allowed("momentum_breakdown", -1, strategy_mode) and ic_filter.get("momentum_breakdown", True):
                contributions.append(("momentum_breakdown", -1, st, -STRENGTH_WEIGHT[st]))

        # Drawdown stop SELL
        if ret_20d is not None and ret_20d < thresholds["drawdown_20d"]:
            st = "strong" if (ret_20d and ret_20d < -20) else "moderate"
            if _is_rule_allowed("drawdown_stop", -1, strategy_mode) and ic_filter.get("drawdown_stop", True):
                contributions.append(("drawdown_stop", -1, st, -STRENGTH_WEIGHT[st]))

        # Death cross SELL
        if (sma_50 and sma_200 and sma_200 > 0 and close_val
                and close_val < sma_50 and sma_50 < sma_200):
            sma_ratio = sma_50 / sma_200
            if 0.99 <= sma_ratio <= 1.01:
                if _is_rule_allowed("death_cross", -1, strategy_mode) and ic_filter.get("death_cross", True):
                    contributions.append(("death_cross", -1, "strong", -2.0))

        # Resolve ensemble: sum all contributions
        total_score = sum(c[3] for c in contributions)
        # Regime filter: in strong_downtrend, require stronger conviction for BUY
        buy_threshold = 2.0 if trend_state == "strong_downtrend" else 1.0
        if total_score >= buy_threshold:
            signal = 1
            best = max(contributions, key=lambda x: abs(x[3]))
            signal_rule = best[0]
            signal_strength = best[2]
        elif total_score <= -1.0:
            signal = -1
            best = min(contributions, key=lambda x: x[3])
            signal_rule = best[0]
            signal_strength = best[2]
        else:
            signal = 0
            signal_rule = None
            signal_strength = None


        rows.append({
            "date": d,
            "close": close_val,
            "high": high_val,
            "low": low_val,
            "rsi": rsi,
            "52w_position": pos_52w,
            "5d_return": ret_5d,
            "volume_ratio": vol_ratio,
            "boll_lb": boll_lb,
            "ret_20d": ret_20d,
            "atr": atr,
            "trend_state": trend_state,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "ret_10d": ret_10d,
            "signal": signal,
            "signal_rule": signal_rule,
            "signal_strength": signal_strength,
        })

    return pd.DataFrame(rows)


def _build_trade(entry_date, exit_date, entry_price, exit_price, ret,
                 exit_reason, highest_since_entry, lowest_since_entry,
                 entry_signal_rule=None, direction="long",
                 trend_state_at_entry=None):
    """Build a trade dict with computed metrics.

    direction: "long" or "short". MAE/MFE are direction-aware:
    - long:  MAE = max drawdown from entry (lowest), MFE = max gain (highest)
    - short: MAE = max adverse move from entry (highest), MFE = max gain (lowest)
    """
    entry_dt = pd.to_datetime(entry_date)
    exit_dt = pd.to_datetime(exit_date)
    holding_days = (exit_dt - entry_dt).days
    if direction == "short":
        mae_pct = (highest_since_entry - entry_price) / entry_price * 100
        mfe_pct = (lowest_since_entry - entry_price) / entry_price * 100
    else:
        mae_pct = (lowest_since_entry - entry_price) / entry_price * 100
        mfe_pct = (highest_since_entry - entry_price) / entry_price * 100

    # MFE capture ratio (A-US-003) — direction-aware
    if direction == "long":
        denom_mfe = highest_since_entry - entry_price
        if denom_mfe != 0:
            mfe_capture_pct = (exit_price - entry_price) / denom_mfe * 100
        else:
            mfe_capture_pct = None
    else:
        denom_mfe = entry_price - lowest_since_entry
        if denom_mfe != 0:
            mfe_capture_pct = (entry_price - exit_price) / denom_mfe * 100
        else:
            mfe_capture_pct = None

    # Exit Timing Score (A-US-003)
    mfe_range = mfe_pct / 100.0 if mfe_pct else 0.0
    mae_range = mae_pct / 100.0 if mae_pct else 0.0
    denom_ee = mfe_range - mae_range
    if mfe_capture_pct is not None and denom_ee > 0:
        exit_efficiency = (mfe_range - abs(ret)) / denom_ee
    else:
        exit_efficiency = None

    trade = {
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "return": ret,
        "exit_reason": exit_reason,
        "holding_days": holding_days,
        "mae_pct": round(mae_pct, 2),
        "mfe_pct": round(mfe_pct, 2),
        "direction": direction,
        "mfe_capture_pct": round(mfe_capture_pct, 2) if mfe_capture_pct is not None else None,
        "exit_efficiency": round(exit_efficiency, 4) if exit_efficiency is not None else None,
    }
    if entry_signal_rule:
        trade["entry_signal_rule"] = entry_signal_rule
    if trend_state_at_entry:
        trade["trend_state_at_entry"] = trend_state_at_entry
    return trade


def _compute_realized_vol(returns_window: list, annualize: bool = True) -> float:
    """Compute realized volatility from a list of daily returns."""
    if len(returns_window) < 2:
        return 0.0
    mean = sum(returns_window) / len(returns_window)
    var = sum((r - mean) ** 2 for r in returns_window) / (len(returns_window) - 1)
    daily_vol = math.sqrt(var) if var > 0 else 0.0
    return daily_vol * math.sqrt(252) if annualize else daily_vol


def _close_position(entry_date, exit_date, entry_price, close, ret, exit_reason,
                    position, entry_rule, trend_state, vol_mult,
                    high_since, low_since, actual_shares, margin_accrued,
                    margin_mode, ticker, vol_ratio, cost_params,
                    trades, daily_returns, total_tc):
    """Record a trade, compute costs, reset position state. Returns updated state dict."""
    direction = "long" if position == 1 else "short"
    cost = round(margin_accrued, 2) if margin_mode else 0.0
    trade = _build_trade(
        entry_date, exit_date, entry_price, close, ret,
        exit_reason, high_since, low_since,
        entry_rule, direction,
        trend_state_at_entry=trend_state,
    )
    trade["margin_cost"] = cost
    trade["vol_multiplier"] = round(vol_mult, 4)
    tc = _compute_transaction_cost(close, actual_shares, ticker, vol_ratio, cost_params)
    trade["transaction_cost"] = tc
    trade["return_after_cost"] = round(ret - (cost + tc["total"]) / (entry_price * actual_shares), 6)
    trade["shares"] = actual_shares
    trades.append(trade)
    total_tc += tc["total"]
    if daily_returns:
        daily_returns[-1] -= tc["total"] / (entry_price * actual_shares)
    return {
        "total_transaction_cost": total_tc,
        "position": 0, "entry_price": 0, "entry_date": None,
        "entry_signal_rule": None, "entry_trend_state": None,
        "highest_since_entry": 0.0, "lowest_since_entry": 0.0,
        "margin_cost_accrued": 0.0,
    }


def simulate_trades(signals_df: pd.DataFrame, risk_params: dict = None,
                    margin_mode: bool = False,
                    margin_params: dict = None,
                    ticker: str = "",
                    cost_params: dict = None,
                    execution_delay: int = 0) -> dict:
    """Simulate trades from signal DataFrame and compute performance metrics.

    One position at a time. When margin_mode=True, short selling and margin
    costs are enabled. Uses closing prices.

    Trailing stop (ATR-based) is checked before signal processing each day.
    If triggered, the day's signal is skipped to prevent re-entry on the
    same day as a stop-out.

    When cost_params is provided (or defaults active), transaction costs
    (commission, slippage, market impact) are deducted from each trade.
    Set cost_params=None to disable.

    execution_delay > 0 introduces a T+1 delay between signal detection and
    execution. Signal on day T executes at day T+1 close. Last-row signals
    are skipped. Default 0 = same-day (backward compatible).
    """
    if risk_params is None:
        risk_params = DEFAULT_RISK_PARAMS
    if margin_params is None:
        margin_params = DEFAULT_MARGIN_PARAMS
    if cost_params is None:
        cost_params = DEFAULT_COST_PARAMS
    atr_mult_map = risk_params["trailing_stop_atr_mult"]
    slew_max = risk_params.get("atr_slew_max", 0.5)
    margin_long_rate = margin_params["margin_long_rate"]
    margin_short_rate = margin_params["margin_short_rate"]
    margin_max_days = margin_params["margin_max_days"]

    SHORT_TREND_GATE = {"strong_downtrend", "downtrend"}

    if signals_df.empty:
        return _empty_metrics()

    trades = []
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0
    entry_date = None
    entry_signal_rule = None
    entry_trend_state = None
    entry_vol_multiplier = 1.0
    highest_since_entry = 0.0
    lowest_since_entry = 0.0
    prev_effective_mult = 0.0
    margin_cost_accrued = 0.0  # yen, accumulated per trade
    total_transaction_cost = 0.0  # yen, accumulated across all trades
    returns_window = []  # last N daily returns for realized vol
    vol_lookback = risk_params.get("vol_lookback", 20)
    vol_target = risk_params.get("vol_target", 0.15)
    vol_target_min = risk_params.get("vol_target_min", 0.5)
    vol_target_max = risk_params.get("vol_target_max", 2.0)

    daily_returns = []
    prev_close = None
    prev_position = 0
    pending_signal = None  # (signal_val, signal_rule) buffered for T+1 execution

    for _, row in signals_df.iterrows():
        close = row["close"]
        if close <= 0:
            continue

        # Daily return based on previous day's position state
        if prev_close is not None and prev_close > 0:
            if prev_position == 1:
                daily_returns.append((close - prev_close) / prev_close)
            elif prev_position == -1:
                daily_returns.append((prev_close - close) / prev_close)
            else:
                daily_returns.append(0.0)
        prev_close = close

        # Update realized vol window
        if daily_returns:
            returns_window.append(daily_returns[-1])
            if len(returns_window) > vol_lookback:
                returns_window.pop(0)

        # Compute vol multiplier from realized vol
        realized_vol = _compute_realized_vol(returns_window)
        if realized_vol > 0 and vol_target > 0:
            vol_multiplier = max(vol_target_min,
                                 min(vol_target_max, vol_target / realized_vol))
        else:
            vol_multiplier = 1.0

        # Position sizing: base 100 shares scaled by vol_multiplier (0.5–2.0).
        # Floor 100, ceiling 200, rounded to 100-share lots.
        raw = max(100, min(round(100 * vol_multiplier / 100) * 100, 200))
        actual_shares = max(100, min(raw, 200))

        # Margin cost daily accrual
        if margin_mode and position != 0:
            rate = margin_long_rate if position == 1 else margin_short_rate
            margin_cost_accrued += entry_price * (rate / 365)
            daily_returns[-1] -= (rate / 365)

        # Adaptive ATR multiplier from trend state with slew limiting
        trend_state = row.get("trend_state", "unknown")
        target_mult = atr_mult_map.get(trend_state, 3.0)
        if prev_effective_mult > 0:
            change = target_mult - prev_effective_mult
            change = max(-slew_max, min(slew_max, change))
            effective_mult = prev_effective_mult + change
        else:
            effective_mult = target_mult

        # Trailing stop check (before signal processing)
        if position != 0:
            row_high = row.get("high", close) or close
            row_low = row.get("low", close) or close
            if row_high > highest_since_entry:
                highest_since_entry = row_high
            if row_low < lowest_since_entry:
                lowest_since_entry = row_low
            atr_val = row.get("atr")
            if atr_val is not None and not (isinstance(atr_val, float) and math.isnan(atr_val)):
                stopped = False
                if position == 1:
                    stop_level = highest_since_entry - (atr_val * effective_mult)
                    stopped = close < stop_level
                else:  # short
                    stop_level = lowest_since_entry + (atr_val * effective_mult)
                    stopped = close > stop_level
                if stopped:
                    if position == 1:
                        ret = (close - entry_price) / entry_price
                    else:
                        ret = (entry_price - close) / entry_price
                    cost = round(margin_cost_accrued, 2) if margin_mode else 0.0
                    direction = "long" if position == 1 else "short"
                    trade = _build_trade(
                        entry_date, row["date"], entry_price, close, ret,
                        "trailing_stop", highest_since_entry, lowest_since_entry,
                        entry_signal_rule, direction,
                        trend_state_at_entry=entry_trend_state,
                    )
                    trade["margin_cost"] = cost
                    trade["vol_multiplier"] = round(entry_vol_multiplier, 4)
                    tc = _compute_transaction_cost(close, actual_shares, ticker,
                                                   row.get("volume_ratio", 1.0),
                                                   cost_params)
                    trade["transaction_cost"] = tc
                    trade["return_after_cost"] = round(ret - (cost + tc["total"]) / (entry_price * actual_shares), 6)
                    total_transaction_cost += tc["total"]
                    if daily_returns:
                        daily_returns[-1] -= tc["total"] / (entry_price * actual_shares)
                    trade["shares"] = actual_shares
                    trades.append(trade)
                    position = 0
                    entry_price = 0
                    entry_date = None
                    entry_signal_rule = None
                    entry_trend_state = None
                    highest_since_entry = 0.0
                    lowest_since_entry = 0.0
                    margin_cost_accrued = 0.0
                    prev_position = 0
                    continue

        prev_effective_mult = effective_mult

        # Margin expiry check
        if margin_mode and position != 0 and entry_date is not None:
            holding_days = (pd.to_datetime(row["date"]) - pd.to_datetime(entry_date)).days
            if holding_days > margin_max_days:
                if position == 1:
                    ret = (close - entry_price) / entry_price
                else:
                    ret = (entry_price - close) / entry_price
                cost = round(margin_cost_accrued, 2)
                direction = "long" if position == 1 else "short"
                trade = _build_trade(
                    entry_date, row["date"], entry_price, close, ret,
                    "margin_expiry", highest_since_entry, lowest_since_entry,
                    entry_signal_rule, direction,
                    trend_state_at_entry=entry_trend_state,
                )
                trade["margin_cost"] = cost
                trade["vol_multiplier"] = round(entry_vol_multiplier, 4)
                tc = _compute_transaction_cost(close, actual_shares, ticker,
                                               row.get("volume_ratio", 1.0),
                                               cost_params)
                trade["transaction_cost"] = tc
                trade["return_after_cost"] = round(ret - (cost + tc["total"]) / (entry_price * actual_shares), 6)
                total_transaction_cost += tc["total"]
                if daily_returns:
                    daily_returns[-1] -= tc["total"] / (entry_price * actual_shares)
                trade["shares"] = actual_shares
                trades.append(trade)
                position = 0
                entry_price = 0
                entry_date = None
                entry_signal_rule = None
                entry_trend_state = None
                highest_since_entry = 0.0
                lowest_since_entry = 0.0
                margin_cost_accrued = 0.0
                prev_position = 0
                # fall through to signal check (which will skip since position==0)
                continue

        # Signal check — state machine
        sig = row["signal"]
        sig_rule = row.get("signal_rule")

        # Execution delay: buffer signal and apply pending
        if execution_delay > 0:
            # Skip signals on the last row (no T+1 to execute)
            is_last = (row.name == signals_df.index[-1])
            if pending_signal is not None:
                sig, sig_rule = pending_signal
                pending_signal = None
            elif not is_last:
                pending_signal = (sig, sig_rule)
                sig = 0
                sig_rule = None
            # If last row and no pending signal: sig at last row is skipped

        if sig == 1:
            if position == 0:
                position = 1
                entry_price = close
                entry_date = row["date"]
                entry_signal_rule = row.get("signal_rule")
                entry_trend_state = row.get("trend_state", "unknown")
                entry_vol_multiplier = vol_multiplier
                highest_since_entry = close
                lowest_since_entry = close
                margin_cost_accrued = 0.0
            elif position == -1:
                # Cover short, enter long (same-day flip)
                ret = (entry_price - close) / entry_price
                cost = round(margin_cost_accrued, 2) if margin_mode else 0.0
                trade = _build_trade(
                    entry_date, row["date"], entry_price, close, ret,
                    "signal", highest_since_entry, lowest_since_entry,
                    entry_signal_rule, "short",
                    trend_state_at_entry=entry_trend_state,
                )
                trade["margin_cost"] = cost
                trade["vol_multiplier"] = round(entry_vol_multiplier, 4)
                tc = _compute_transaction_cost(close, actual_shares, ticker,
                                               row.get("volume_ratio", 1.0),
                                               cost_params)
                trade["transaction_cost"] = tc
                trade["return_after_cost"] = round(ret - (cost + tc["total"]) / (entry_price * actual_shares), 6)
                total_transaction_cost += tc["total"]
                if daily_returns:
                    daily_returns[-1] -= tc["total"] / (entry_price * actual_shares)
                trade["shares"] = actual_shares
                trades.append(trade)
                position = 1
                entry_price = close
                entry_date = row["date"]
                entry_signal_rule = row.get("signal_rule")
                entry_trend_state = row.get("trend_state", "unknown")
                entry_vol_multiplier = vol_multiplier
                highest_since_entry = close
                lowest_since_entry = close
                margin_cost_accrued = 0.0
            # else position==1: hold

        elif sig == -1:
            if position == 1:
                # Close long
                ret = (close - entry_price) / entry_price
                state = _close_position(
                    entry_date, row["date"], entry_price, close, ret, "signal",
                    position, entry_signal_rule, entry_trend_state, entry_vol_multiplier,
                    highest_since_entry, lowest_since_entry, actual_shares,
                    margin_cost_accrued, margin_mode, ticker,
                    row.get("volume_ratio", 1.0), cost_params,
                    trades, daily_returns, total_transaction_cost)
                total_transaction_cost = state["total_transaction_cost"]
                position = state["position"]
                entry_price = state["entry_price"]
                entry_date = state["entry_date"]
                entry_signal_rule = state["entry_signal_rule"]
                entry_trend_state = state["entry_trend_state"]
                entry_vol_multiplier = 1.0
                highest_since_entry = state["highest_since_entry"]
                lowest_since_entry = state["lowest_since_entry"]
                margin_cost_accrued = state["margin_cost_accrued"]
                # Try short entry (gated by trend state)
                if margin_mode and trend_state in SHORT_TREND_GATE:
                    position = -1
                    entry_price = close
                    entry_date = row["date"]
                    entry_signal_rule = row.get("signal_rule")
                    entry_trend_state = row.get("trend_state", "unknown")
                    entry_vol_multiplier = vol_multiplier
                    highest_since_entry = close
                    lowest_since_entry = close
                    margin_cost_accrued = 0.0
            elif position == 0:
                # Short entry (gated by trend state)
                if margin_mode and trend_state in SHORT_TREND_GATE:
                    position = -1
                    entry_price = close
                    entry_date = row["date"]
                    entry_signal_rule = row.get("signal_rule")
                    entry_trend_state = row.get("trend_state", "unknown")
                    entry_vol_multiplier = vol_multiplier
                    highest_since_entry = close
                    lowest_since_entry = close
                    margin_cost_accrued = 0.0
            # else position==-1: hold

        prev_position = position

    # Close any open position at the last price
    if position != 0:
        last_row = signals_df.iloc[-1]
        if position == 1:
            ret = (last_row["close"] - entry_price) / entry_price
        else:
            ret = (entry_price - last_row["close"]) / entry_price
        state = _close_position(
            entry_date, last_row["date"], entry_price, last_row["close"], ret, "end_of_period",
            position, entry_signal_rule, entry_trend_state, entry_vol_multiplier,
            highest_since_entry, lowest_since_entry, actual_shares,
            margin_cost_accrued, margin_mode, ticker,
            last_row.get("volume_ratio", 1.0), cost_params,
            trades, daily_returns, total_transaction_cost)
        total_transaction_cost = state["total_transaction_cost"]

    return _compute_metrics(trades, daily_returns, total_transaction_cost)


def compute_signal_census(signals_df, trades):
    """Compute per-rule signal counts and win rates from signal_rule column and trade data.

    BUY rules (signal=1) are entry rules — win rate is meaningful.
    SELL rules (signal=-1) are exit rules — counted but no win rate.
    SHORT type is assigned when a trade with direction="short" uses the rule.
    """
    census = {}
    buy_count = 0
    sell_count = 0
    if "signal_rule" in signals_df.columns:
        for _, row in signals_df.iterrows():
            rule = row.get("signal_rule")
            sig = row["signal"]
            if not rule or sig == 0:
                continue
            if sig == 1:
                buy_count += 1
            elif sig == -1:
                sell_count += 1
            if rule not in census:
                rule_type = "entry" if sig == 1 else "exit"
                census[rule] = {"count": 0, "type": rule_type}
            census[rule]["count"] += 1

    rule_trades = {}
    for t in trades:
        rule = t.get("entry_signal_rule")
        if not rule:
            continue
        if rule not in rule_trades:
            rule_trades[rule] = {"wins": 0, "total": 0}
        rule_trades[rule]["total"] += 1
        if t["return"] > 0:
            rule_trades[rule]["wins"] += 1

    for rule, rt in rule_trades.items():
        if rule in census and census[rule]["type"] == "entry":
            census[rule]["win_rate"] = round(rt["wins"] / rt["total"] * 100, 2)
        elif rule not in census:
            census[rule] = {"count": 0, "type": "entry", "win_rate": round(rt["wins"] / rt["total"] * 100, 2)}

    short_count = 0
    for t in trades:
        if t.get("direction") == "short":
            short_count += 1
            rule = t.get("entry_signal_rule")
            if rule and rule in census:
                census[rule]["type"] = "SHORT"
        elif t.get("direction") == "long":
            rule = t.get("entry_signal_rule")
            if rule and rule in census and census[rule]["type"] == "exit":
                census[rule]["type"] = "SELL"

    census["totals"] = {"buy_count": buy_count, "sell_count": sell_count, "short_count": short_count}
    return census


def compute_signal_ic(signals_df: pd.DataFrame) -> dict:
    """Compute Information Coefficient (Spearman correlation) per signal rule.

    IC measures predictive power by correlating signal direction with
    forward returns at 5d, 10d, 20d horizons. t-stat > 2 = significant.
    """
    if signals_df.empty or "close" not in signals_df.columns:
        return {}
    closes = signals_df["close"].values
    ic_results = {}
    for horizon, label in [(5, "5d"), (10, "10d"), (20, "20d")]:
        if len(closes) <= horizon:
            continue
        fwd_ret = np.zeros(len(closes))
        fwd_ret[:-horizon] = (closes[horizon:] - closes[:-horizon]) / closes[:-horizon]
        rule_data = {}
        for idx, row in signals_df.iterrows():
            rule, sig = row.get("signal_rule"), row.get("signal", 0)
            if not rule or sig == 0:
                continue
            pos = signals_df.index.get_loc(idx) if idx in signals_df.index else idx
            if isinstance(pos, int) and pos < len(fwd_ret):
                rule_data.setdefault(rule, {"signals": [], "fwd": []})
                rule_data[rule]["signals"].append(sig)
                rule_data[rule]["fwd"].append(fwd_ret[pos])
        per_rule = {}
        for rule, d in rule_data.items():
            s, fw = np.array(d["signals"]), np.array(d["fwd"])
            if len(s) < 5:
                continue
            try:
                from scipy.stats import spearmanr
                ic, pval = spearmanr(s, fw)
            except ImportError:
                ic = np.corrcoef(s, fw)[0, 1] if len(s) > 1 else 0
                pval = None
            n = len(s)
            denom = max(1 - ic * ic, 0.0001)
            t_stat = ic * np.sqrt((n - 2) / denom) if abs(ic) < 1 else 0
            per_rule[rule] = {
                "ic": round(float(ic), 4), "n_signals": n,
                "t_stat": round(float(t_stat), 2),
                "significant": abs(t_stat) > 2,
                "p_value": round(float(pval), 4) if pval is not None else None,
            }
        if per_rule:
            ic_results[label] = per_rule
    return ic_results


def _empty_metrics():
    return {
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "cagr": 0.0,
        "total_return": 0.0,
        "calmar_ratio": 0.0,
        "trade_count": 0,
        "avg_holding_days": 0.0,
        "max_consecutive_wins": 0,
        "max_consecutive_losses": 0,
        "avg_win_pct": 0.0,
        "avg_loss_pct": 0.0,
        "total_margin_cost": 0.0,
        "trades": [],
        "regime_breakdown": {},
        "avg_mfe_capture_pct": None,
        "avg_exit_efficiency": None,
        "early_exit_count": 0,
        "var_95": None,
        "var_99": None,
        "cvar_95": None,
        "cvar_99": None,
        "skewness": None,
        "kurtosis": None,
        "sharpe_ci_lower": None,
        "sharpe_ci_upper": None,
        "deflated_sharpe": None,
    }


def _compute_metrics(trades: list, daily_returns: list,
                     total_transaction_cost: float = 0.0) -> dict:
    if not trades:
        metrics = _empty_metrics()
        metrics["daily_return_std"] = float(np.std(daily_returns)) if daily_returns else 0.0
        return metrics

    n = len(trades)
    wins = [t for t in trades if t["return"] > 0]
    losses = [t for t in trades if t["return"] <= 0]

    win_rate = len(wins) / n if n > 0 else 0

    total_win = sum(t["return"] for t in wins) if wins else 0
    total_loss = abs(sum(t["return"] for t in losses)) if losses else 0
    profit_factor = total_win / total_loss if total_loss > 0 else float("inf")

    # CAGR: compound annual growth rate
    if trades:
        first_date = pd.to_datetime(trades[0]["entry_date"])
        last_date = pd.to_datetime(trades[-1]["exit_date"])
        years = (last_date - first_date).days / 365.25
        years = max(years, 1.0 / 252)  # at least 1 trading day
        total_ret = 1.0
        for t in trades:
            total_ret *= (1 + t["return"])
        cagr = (total_ret ** (1.0 / years)) - 1 if years > 0 else 0
    else:
        cagr = 0
        total_ret = 0

    # Daily equity curve for drawdown (includes cash periods and margin costs)
    if daily_returns:
        equity = [1.0]
        for dr in daily_returns:
            equity.append(equity[-1] * (1 + dr))
        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        total_return = equity[-1] - 1.0
    else:
        max_dd = 0.0
        total_return = 0.0

    # Sharpe ratio (annualized)
    dr_array = np.array(daily_returns) if daily_returns else np.array([0.0])
    avg_dr = np.mean(dr_array)
    std_dr = np.std(dr_array)
    sharpe = (avg_dr / std_dr * math.sqrt(252)) if std_dr > 0 else 0.0

    # Sortino ratio (annualized, downside deviation only)
    neg_dr = dr_array[dr_array < 0]
    downside_std = np.std(neg_dr) if len(neg_dr) > 0 else 0.0
    sortino = (avg_dr / downside_std * math.sqrt(252)) if downside_std > 0 else 0.0

    # Holding period statistics
    holding_days = [t.get("holding_days", 0) for t in trades]
    avg_holding_days = sum(holding_days) / len(holding_days) if holding_days else 0

    # Win/loss streaks
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    current_streak = 0
    current_type = None
    for t in trades:
        is_win = t["return"] > 0
        if current_type is None or is_win == current_type:
            current_streak += 1
        else:
            current_streak = 1
        current_type = is_win
        if is_win:
            max_consecutive_wins = max(max_consecutive_wins, current_streak)
        else:
            max_consecutive_losses = max(max_consecutive_losses, current_streak)

    # Average win/loss percentages
    avg_win_pct = sum(t["return"] for t in wins) / len(wins) * 100 if wins else 0
    avg_loss_pct = sum(t["return"] for t in losses) / len(losses) * 100 if losses else 0

    # Regime breakdown (A-US-002)
    ALL_REGIMES = ["strong_uptrend", "weak_uptrend", "ranging", "downtrend", "strong_downtrend", "unknown"]
    regime_breakdown = {}
    for regime in ALL_REGIMES:
        rt = [t for t in trades if t.get("trend_state_at_entry") == regime]
        if rt:
            regime_breakdown[regime] = {
                "trade_count": len(rt),
                "win_rate": round(sum(1 for t in rt if t["return"] > 0) / len(rt) * 100, 2),
                "avg_return": round(sum(t["return"] for t in rt) / len(rt) * 100, 2),
                "total_return": round(sum(t["return"] for t in rt) * 100, 2),
            }
        else:
            regime_breakdown[regime] = {"trade_count": 0}

    # Exit efficiency aggregates (A-US-003)
    mfe_caps = [t["mfe_capture_pct"] for t in trades if t.get("mfe_capture_pct") is not None]
    exit_effs = [t["exit_efficiency"] for t in trades if t.get("exit_efficiency") is not None]
    avg_mfe_capture_pct = round(float(np.mean(mfe_caps)), 2) if mfe_caps else None
    avg_exit_efficiency = round(float(np.mean(exit_effs)), 4) if exit_effs else None
    early_exit_count = sum(1 for t in trades if t.get("mfe_capture_pct") is not None and t["mfe_capture_pct"] < 30)

    # Bootstrap Sharpe 95% confidence interval (1000 resamples)
    if len(dr_array) >= 20:
        n_bs = 1000
        np.random.seed(42)
        bs_sharpes = []
        for _ in range(n_bs):
            sample = np.random.choice(dr_array, size=len(dr_array), replace=True)
            m, s = float(np.mean(sample)), float(np.std(sample))
            bs_sharpes.append((m / s * math.sqrt(252)) if s > 0 else 0.0)
        sharpe_ci_lower = round(float(np.percentile(bs_sharpes, 2.5)), 4)
        sharpe_ci_upper = round(float(np.percentile(bs_sharpes, 97.5)), 4)
        # Deflated Sharpe (Bonferroni correction for 256 grid-search combos)
        deflated_sharpe = round(sharpe * (1 - 0.05 / 256), 4)
    else:
        sharpe_ci_lower = sharpe_ci_upper = deflated_sharpe = None

    # Tail-risk metrics from daily returns
    if len(dr_array) >= 20:
        var_95 = round(float(np.percentile(dr_array, 5)) * 100, 4)
        var_99 = round(float(np.percentile(dr_array, 1)) * 100, 4)
        below_95 = dr_array[dr_array <= np.percentile(dr_array, 5)]
        below_99 = dr_array[dr_array <= np.percentile(dr_array, 1)]
        cvar_95 = round(float(np.mean(below_95)) * 100, 4) if len(below_95) > 0 else var_95
        cvar_99 = round(float(np.mean(below_99)) * 100, 4) if len(below_99) > 0 else var_99
        m, s = float(np.mean(dr_array)), float(np.std(dr_array, ddof=1))
        if s > 0 and len(dr_array) >= 3:
            skewness = round(float(np.sum((dr_array - m) ** 3) / len(dr_array) / (s ** 3)), 4)
            kurtosis = round(float(np.sum((dr_array - m) ** 4) / len(dr_array) / (s ** 4)) - 3, 4)
        else:
            skewness = None
            kurtosis = None
    else:
        var_95 = var_99 = cvar_95 = cvar_99 = None
        skewness = None
        kurtosis = None

    return {
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown": round(max_dd * 100, 2),
        "win_rate": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "cagr": round(cagr * 100, 2),
        "total_return": round(total_return * 100, 2),
        "trade_count": n,
        "daily_return_std": round(float(std_dr), 6),
        "trades": trades,
        "calmar_ratio": round(cagr / max(max_dd, 0.0001), 2) if max_dd > 0 else 0,
        "avg_holding_days": round(avg_holding_days, 1) if n > 0 else 0.0,
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
        "avg_win_pct": round(avg_win_pct, 2) if wins else 0.0,
        "avg_loss_pct": round(avg_loss_pct, 2) if losses else 0.0,
        "total_margin_cost": round(sum(t.get("margin_cost", 0) for t in trades), 2),
        "total_transaction_cost": round(total_transaction_cost, 2),
        "total_transaction_cost_per_trade": round(total_transaction_cost / n, 2) if n > 0 else 0.0,
        "regime_breakdown": regime_breakdown,
        "avg_mfe_capture_pct": avg_mfe_capture_pct,
        "avg_exit_efficiency": avg_exit_efficiency,
        "early_exit_count": early_exit_count,
        "var_95": var_95,
        "var_99": var_99,
        "cvar_95": cvar_95,
        "cvar_99": cvar_99,
        "skewness": skewness,
        "kurtosis": kurtosis,
        "sharpe_ci_lower": sharpe_ci_lower,
        "sharpe_ci_upper": sharpe_ci_upper,
        "deflated_sharpe": deflated_sharpe,
    }


def grid_search(ticker: str, start_date: str, end_date: str,
                margin_mode: bool = False) -> dict:
    """Run grid search over threshold parameters.

    When margin_mode=True, passes margin_mode to simulate_trades.
    Grid search continues to use single-split walk_forward per combo.
    """
    results = []
    total = (len(TUNE_PARAM_GRID["rsi_lower"])
             * len(TUNE_PARAM_GRID["rsi_upper"])
             * len(TUNE_PARAM_GRID["position_52w_lower"])
             * len(TUNE_PARAM_GRID["position_52w_upper"]))
    count = 0

    for rsi_low in TUNE_PARAM_GRID["rsi_lower"]:
        for rsi_high in TUNE_PARAM_GRID["rsi_upper"]:
            for pos_low in TUNE_PARAM_GRID["position_52w_lower"]:
                for pos_high in TUNE_PARAM_GRID["position_52w_upper"]:
                    count += 1
                    thresholds = {
                        **DEFAULT_THRESHOLDS,
                        "rsi_lower": rsi_low,
                        "rsi_upper": rsi_high,
                        "position_52w_lower": pos_low,
                        "position_52w_upper": pos_high,
                    }
                    sig_df = generate_signals(ticker, start_date, end_date, thresholds)
                    metrics = simulate_trades(sig_df, ticker=ticker, margin_mode=margin_mode)
                    results.append({
                        "thresholds": thresholds,
                        "sharpe_ratio": metrics["sharpe_ratio"],
                        "sortino_ratio": metrics["sortino_ratio"],
                        "max_drawdown": metrics["max_drawdown"],
                        "win_rate": metrics["win_rate"],
                        "profit_factor": metrics["profit_factor"],
                        "cagr": metrics["cagr"],
                        "total_return": metrics["total_return"],
                        "trade_count": metrics["trade_count"],
                        "margin_mode": margin_mode,
                    })

    results.sort(key=lambda r: r["sharpe_ratio"], reverse=True)
    return {"grid_results": results, "combinations_tested": total}


def walk_forward(ticker: str, start_date: str, end_date: str,
                 thresholds: dict = None, risk_params: dict = None,
                 margin_mode: bool = False,
                 strategy_mode: str = "default",
                 embargo_days: int = 5,
                 overfit_threshold: float = 50.0,
                 execution_delay: int = 0) -> dict:
    """Walk-forward analysis: 70% train / 30% test split with purging.

    Train on first 70%, evaluate on last 30%. A purging gap of embargo_days
    separates train and test to prevent leakage from overlapping observations.

    Overfitting guard: if train/test Sharpe degradation > overfit_threshold %
    or test Sharpe < 0, discard tuned thresholds and use defaults.
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if risk_params is None:
        risk_params = DEFAULT_RISK_PARAMS

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    total = (end - start).days
    split_point = start + timedelta(days=int(total * 0.7))
    train_start = start.strftime("%Y-%m-%d")
    train_end = (split_point - timedelta(days=embargo_days)).strftime("%Y-%m-%d")
    test_start = split_point.strftime("%Y-%m-%d")
    test_end = end.strftime("%Y-%m-%d")

    # Train period
    train_sig = generate_signals(ticker, train_start, train_end, thresholds,
                                 strategy_mode=strategy_mode)
    train_metrics = simulate_trades(train_sig, risk_params, ticker=ticker,
                                    margin_mode=margin_mode,
                                    execution_delay=execution_delay)

    # Test period (out-of-sample)
    test_sig = generate_signals(ticker, test_start, test_end, thresholds,
                                strategy_mode=strategy_mode)
    test_metrics = simulate_trades(test_sig, risk_params, ticker=ticker,
                                   margin_mode=margin_mode,
                                   execution_delay=execution_delay)

    # Overfitting guard
    train_sharpe = train_metrics["sharpe_ratio"]
    test_sharpe = test_metrics["sharpe_ratio"]
    if train_sharpe != 0:
        sharpe_diff_pct = abs((train_sharpe - test_sharpe) / train_sharpe) * 100
    else:
        sharpe_diff_pct = 0 if test_sharpe == 0 else 100

    overfit = bool((sharpe_diff_pct > overfit_threshold) or (test_sharpe < 0))
    tuned_thresholds = None
    tuned_test_metrics = None
    if overfit:
        tuned_thresholds = dict(thresholds)
        tuned_test_metrics = dict(test_metrics)
        thresholds = DEFAULT_THRESHOLDS
        risk_params = DEFAULT_RISK_PARAMS
        test_sig = generate_signals(ticker, test_start, test_end, thresholds,
                                    strategy_mode=strategy_mode)
        test_metrics = simulate_trades(test_sig, risk_params, ticker=ticker,
                                       margin_mode=margin_mode,
                                       execution_delay=execution_delay)

    result = {
        "train_period": {"start": train_start, "end": train_end},
        "test_period": {"start": test_start, "end": test_end},
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "sharpe_diff_pct": round(sharpe_diff_pct, 2),
        "overfit_detected": overfit,
        "thresholds_used": thresholds,
    }
    if tuned_thresholds is not None:
        result["tuned_thresholds"] = tuned_thresholds
    if tuned_test_metrics is not None:
        result["tuned_test_metrics"] = tuned_test_metrics
    return result


def walk_forward_rolling(ticker: str, start_date: str, end_date: str,
                         thresholds: dict = None, risk_params: dict = None,
                         margin_mode: bool = False, n_windows: int = 5,
                         strategy_mode: str = "default",
                         embargo_days: int = 5,
                         execution_delay: int = 0) -> dict:
    """Rolling walk-forward with N sequential non-overlapping windows.

    Each window is an independent 70/30 train/test split using sequential
    (non-nested) date ranges. A purging gap of embargo_days separates train
    and test within each window. Returns per-window results, consensus verdict,
    and backward-compatible legacy keys from window 0.
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if risk_params is None:
        risk_params = DEFAULT_RISK_PARAMS

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    total_days = (end - start).days
    if total_days < 10:
        result = dict(walk_forward(ticker, start_date, end_date, thresholds,
                                   risk_params, margin_mode,
                                   strategy_mode=strategy_mode,
                                   embargo_days=embargo_days,
                                   execution_delay=execution_delay))
        result["rolling_windows"] = []
        result["consensus"] = {
            "mean_sharpe": result["test_metrics"]["sharpe_ratio"],
            "std_sharpe": 0.0,
            "mean_maxdd": result["test_metrics"]["max_drawdown"],
            "mean_win_rate": result["test_metrics"]["win_rate"],
            "overfit_count": 1 if result["overfit_detected"] else 0,
            "verdict": "data_insufficient",
        }
        return result

    if total_days < 252:
        result = dict(walk_forward(ticker, start_date, end_date, thresholds,
                                   risk_params, margin_mode,
                                   strategy_mode=strategy_mode,
                                   embargo_days=embargo_days,
                                   execution_delay=execution_delay))
        result["rolling_windows"] = []
        result["consensus"] = {
            "mean_sharpe": result["test_metrics"]["sharpe_ratio"],
            "std_sharpe": 0.0,
            "mean_maxdd": result["test_metrics"]["max_drawdown"],
            "mean_win_rate": result["test_metrics"]["win_rate"],
            "overfit_count": 1 if result["overfit_detected"] else 0,
            "verdict": "data_insufficient",
        }
        return result

    # Generate n_windows sequential non-overlapping windows using half-open
    # date ranges [start, end). Each window spans per_window_range days.
    per_window_range = total_days // n_windows

    rolling_windows = []
    for i in range(n_windows):
        w_start = start + timedelta(days=i * per_window_range)
        w_end = start + timedelta(days=(i + 1) * per_window_range)

        wf = walk_forward(ticker, w_start.strftime("%Y-%m-%d"),
                          w_end.strftime("%Y-%m-%d"),
                          thresholds, risk_params, margin_mode,
                          strategy_mode=strategy_mode,
                          embargo_days=embargo_days,
                          execution_delay=execution_delay)
        rolling_windows.append({
            "window": i,
            "train_start": wf["train_period"]["start"],
            "train_end": wf["train_period"]["end"],
            "test_start": wf["test_period"]["start"],
            "test_end": wf["test_period"]["end"],
            "train_metrics": wf["train_metrics"],
            "test_metrics": wf["test_metrics"],
            "sharpe_diff_pct": wf["sharpe_diff_pct"],
            "overfit_detected": wf["overfit_detected"],
        })

    # Consensus
    test_sharpes = [rw["test_metrics"]["sharpe_ratio"] for rw in rolling_windows]
    mean_sharpe = float(np.mean(test_sharpes))
    std_sharpe = float(np.std(test_sharpes))
    mean_maxdd = float(np.mean([rw["test_metrics"]["max_drawdown"] for rw in rolling_windows]))
    mean_win_rate = float(np.mean([rw["test_metrics"]["win_rate"] for rw in rolling_windows]))
    overfit_count = sum(1 for rw in rolling_windows if rw["overfit_detected"])

    total_trades = sum(rw["test_metrics"]["trade_count"] for rw in rolling_windows)
    if total_trades == 0:
        verdict = "no_trades"
    else:
        if overfit_count > 2:
            verdict = "insufficient_data"
        elif overfit_count > 0:
            verdict = "unstable"
        elif std_sharpe < 0.5:
            verdict = "robust"
        else:
            verdict = "stable"

    # Backward compatibility shim: legacy keys from window 0
    w0 = rolling_windows[0]
    result = {
        "rolling_windows": rolling_windows,
        "consensus": {
            "mean_sharpe": round(mean_sharpe, 4),
            "std_sharpe": round(std_sharpe, 4),
            "mean_maxdd": round(mean_maxdd, 2),
            "mean_win_rate": round(mean_win_rate, 2),
            "overfit_count": overfit_count,
            "verdict": verdict,
        },
        "train_metrics": w0["train_metrics"],
        "test_metrics": w0["test_metrics"],
        "sharpe_diff_pct": w0["sharpe_diff_pct"],
        "overfit_detected": w0["overfit_detected"],
        "thresholds_used": thresholds,
    }
    return result


def _compute_benchmark(ohlcv: pd.DataFrame, start_date: str, end_date: str) -> dict:
    """Compute buy-and-hold CAGR, MaxDD, Sharpe, total_return over the same period as strategy."""
    df = ohlcv.copy()
    df["date_str"] = df["Date"].dt.strftime("%Y-%m-%d")
    mask = (df["date_str"] >= start_date) & (df["date_str"] <= end_date)
    period = df[mask].copy()
    if period.empty:
        return {"cagr": 0.0, "max_drawdown": 0.0, "sharpe_ratio": 0.0, "total_return": 0.0}

    closes = period["Close"].values
    first_close = closes[0]
    last_close = closes[-1]
    total_return = (last_close - first_close) / first_close

    # CAGR
    first_date = pd.to_datetime(period["Date"].iloc[0])
    last_date = pd.to_datetime(period["Date"].iloc[-1])
    years = max((last_date - first_date).days / 365.25, 1.0 / 252)
    cagr = ((1 + total_return) ** (1.0 / years)) - 1 if total_return > -1 else -1.0

    # Max drawdown
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (peak - c) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe from daily returns
    daily_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            daily_returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
    dr_array = np.array(daily_returns) if daily_returns else np.array([0.0])
    avg_dr = np.mean(dr_array)
    std_dr = np.std(dr_array)
    sharpe = (avg_dr / std_dr * math.sqrt(252)) if std_dr > 0 else 0.0

    return {
        "cagr": round(cagr * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 4),
        "total_return": round(total_return * 100, 2),
    }


def _print_summary(result):
    """Print human-readable backtest summary (ASCII tables, 80-char width)."""
    b = result["baseline"]
    bm = result["benchmark"]
    wf = result["walk_forward"]

    sep = "=" * 72
    sep2 = "-" * 72
    exit_jp = {"signal": "シグナル", "trailing_stop": "損切り", "end_of_period": "期間終了",
               "margin_expiry": "期限切れ"}

    # Header
    print(f"\n{sep}")
    print(f"  バックテスト サマリー")
    print(f"  銘柄: {result['ticker']}")
    print(f"  期間: {result['period']['start']} 〜 {result['period']['end']}")
    print(sep)

    # Benchmark vs Strategy comparison
    total_mc = sum(t.get("margin_cost", 0) for t in b.get("trades", []))
    print(f"\n  ベンチマーク vs ストラテジー")
    print(f"  {sep2}")
    print(f"  {'指標':<28} {'買い持ち':>12} {'ストラテジー':>14} {'差分':>14}")
    print(f"  {sep2}")

    rows_bm = [
        ("CAGR (%)", bm["cagr"], b["cagr"], b["cagr"] - bm["cagr"]),
        ("最大DD (%)", bm["max_drawdown"], b["max_drawdown"], b["max_drawdown"] - bm["max_drawdown"]),
        ("シャープレシオ", bm["sharpe_ratio"], b["sharpe_ratio"], b["sharpe_ratio"] - bm["sharpe_ratio"]),
        ("総リターン (%)", bm["total_return"], b["total_return"], b["total_return"] - bm["total_return"]),
    ]
    for label, bh, st, delta in rows_bm:
        d_str = f"+{delta:.2f}" if delta > 0 else f"{delta:.2f}"
        print(f"  {label:<28} {bh:>12.2f} {st:>14.2f} {d_str:>14}")

    if total_mc > 0:
        print(f"  {'信用コスト合計 (円)':<28} {'':>12} {total_mc:>14.2f}")

    # Direction split (when margin mode active)
    longs = [t for t in b.get("trades", []) if t.get("direction") == "long"]
    shorts = [t for t in b.get("trades", []) if t.get("direction") == "short"]
    if shorts:
        l_win = sum(1 for t in longs if t["return"] > 0) / len(longs) * 100 if longs else 0
        s_win = sum(1 for t in shorts if t["return"] > 0) / len(shorts) * 100 if shorts else 0
        l_ret = sum(t["return"] for t in longs) * 100 if longs else 0
        s_ret = sum(t["return"] for t in shorts) * 100 if shorts else 0
        print(f"  {'  ロング (件数/勝率/累積)':<28} {len(longs):>4}件 {l_win:>5.1f}% {l_ret:>+8.2f}%")
        print(f"  {'  ショート (件数/勝率/累積)':<28} {len(shorts):>4}件 {s_win:>5.1f}% {s_ret:>+8.2f}%  "
              f"(買い持ち: {bm['total_return']:.1f}%)")
        # A-US-005: contextual note when short underperforms
        if s_win < 30:
            print(f"  {'  注記':<28} ショート戦略は強気相場ではアンダーパフォームしやすい。"
                  f"逆張りエントリのゲーティング設定を見直す場合は --margin オプションを参照。")

    # Regime breakdown (A-US-002)
    regime_bd = b.get("regime_breakdown", {})
    if regime_bd:
        regime_jp = {
            "strong_uptrend": "強気↑↑", "weak_uptrend": "弱気↑", "ranging": "横ばい",
            "downtrend": "下落↓", "strong_downtrend": "暴落↓↓", "unknown": "不明",
        }
        print(f"\n  レジーム別パフォーマンス")
        print(f"  {sep2}")
        print(f"  {'レジーム':<18} {'件数':>5} {'勝率':>8} {'平均R':>8} {'累積R':>8}")
        print(f"  {sep2}")
        for regime in ["strong_uptrend", "weak_uptrend", "ranging", "downtrend", "strong_downtrend", "unknown"]:
            rd = regime_bd.get(regime, {})
            cnt = rd.get("trade_count", 0)
            if cnt > 0:
                print(f"  {regime_jp.get(regime, regime):<18} {cnt:>5} {rd['win_rate']:>7.1f}% "
                      f"{rd['avg_return']:>+7.2f}% {rd['total_return']:>+7.2f}%")
            else:
                print(f"  {regime_jp.get(regime, regime):<18} {cnt:>5}")

    # Exit efficiency (A-US-003)
    avg_mfe = b.get("avg_mfe_capture_pct")
    avg_ee = b.get("avg_exit_efficiency")
    early_exit = b.get("early_exit_count", 0)
    if avg_mfe is not None or avg_ee is not None:
        print(f"\n  イグジット効率")
        print(f"  {sep2}")
        if avg_mfe is not None:
            print(f"  {'平均MFEキャプチャ率':<28} {avg_mfe:>6.1f}%")
        if avg_ee is not None:
            print(f"  {'平均イグジット効率':<28} {avg_ee:>6.4f}")
        if early_exit > 0:
            print(f"  {'早期イグジット回数 (MFE<30%)':<28} {early_exit:>6}")

    # Signal census
    sc = b.get("signal_census", {})
    print(f"\n  シグナル分布")
    print(f"  {sep2}")
    totals = sc.get("totals", {})
    buy_total = totals.get("buy_count", 0)
    sell_total = totals.get("sell_count", 0)
    short_total = totals.get("short_count", 0)
    parts = [f"買: {buy_total}", f"売: {sell_total}"]
    if short_total > 0:
        parts.append(f"空売: {short_total}")
    print(f"  総シグナル数: {buy_total + sell_total}  ({', '.join(parts)})")
    print(f"  {sep2}")
    print(f"  {'ルール':<24} {'種別':>6} {'回数':>7} {'勝率':>10}")
    print(f"  {sep2}")

    type_label = {"entry": "買", "exit": "売", "SELL": "売", "SHORT": "空売"}
    for rule_name in sorted(sc):
        if rule_name == "totals":
            continue
        info = sc[rule_name]
        rtype = info.get("type", "不明")
        type_jp = type_label.get(rtype, "不明")
        wr = info.get("win_rate")
        if rtype in ("entry",):
            wr_str = f"{wr:.1f}%" if wr is not None and info["count"] > 0 else "-"
        else:
            wr_str = "-"  # exit rules have no entry win rate
        print(f"  {rule_name:<24} {type_jp:>6} {info['count']:>7} {wr_str:>10}")

    # Top 3 / Bottom 3 trades
    trades = b.get("trades", [])
    if trades:
        sorted_trades = sorted(trades, key=lambda t: t["return"], reverse=True)
        top3 = sorted_trades[:3]
        bot3 = sorted_trades[-3:]

        print(f"\n  上位3トレード")
        print(f"  {sep2}")
        print(f"  {'エントリー':<12} {'イグジット':<12} {'リターン%':>8} {'日数':>6} {'向':>3} {'ルール':<18} {'理由':<16}")
        print(f"  {sep2}")
        for t in top3:
            d_tag = "S" if t.get("direction") == "short" else " "
            print(f"  {t['entry_date']:<12} {t['exit_date']:<12} {t['return']*100:>7.1f}% {t['holding_days']:>5}  "
                  f"{d_tag:>3} {t.get('entry_signal_rule','N/A'):<18} {exit_jp.get(t['exit_reason'], t['exit_reason']):<16}")

        print(f"\n  下位3トレード")
        print(f"  {sep2}")
        print(f"  {'エントリー':<12} {'イグジット':<12} {'リターン%':>8} {'日数':>6} {'向':>3} {'ルール':<18} {'理由':<16}")
        print(f"  {sep2}")
        for t in reversed(bot3):
            d_tag = "S" if t.get("direction") == "short" else " "
            print(f"  {t['entry_date']:<12} {t['exit_date']:<12} {t['return']*100:>7.1f}% {t['holding_days']:>5}  "
                  f"{d_tag:>3} {t.get('entry_signal_rule','N/A'):<18} {exit_jp.get(t['exit_reason'], t['exit_reason']):<16}")

    # Walk-forward verdict
    print(f"\n  ウォークフォワード判定")
    print(f"  {sep2}")
    has_tuning = "tuning" in result
    overfit = wf["overfit_detected"]
    if has_tuning:
        verdict = "過学習検出" if overfit else "合格"
        print(f"  種別: パラメータ過学習判定")
        print(f"  判定: {verdict}")
    else:
        verdict = "不安定" if overfit else "安定"
        print(f"  種別: レジーム安定性")
        print(f"  判定: {verdict}")
    print(f"  訓練シャープ: {wf['train_metrics']['sharpe_ratio']:.4f}  |  "
          f"テストシャープ: {wf['test_metrics']['sharpe_ratio']:.4f}")
    print(f"  シャープ差: {wf['sharpe_diff_pct']:.1f}%")
    if overfit:
        if has_tuning:
            print(f"  理由: ", end="")
            reasons = []
            if wf["sharpe_diff_pct"] > 50:
                reasons.append(f"訓練/テスト シャープ乖離 {wf['sharpe_diff_pct']:.1f}% > 50%")
            if wf["test_metrics"]["sharpe_ratio"] < 0:
                reasons.append(f"テストシャープ {wf['test_metrics']['sharpe_ratio']:.4f} < 0")
            print("; ".join(reasons))
            if wf.get("tuned_thresholds"):
                print(f"  調整閾値を破棄、デフォルト値を使用")
        else:
            print(f"  注記: --tune なしのため、閾値パラメータの過学習ではなくレジーム安定性を測定")
    else:
        if has_tuning:
            print(f"  過学習未検出。調整閾値は信頼できます。")

    # Strategy comparison (US-003)
    strategy_comparison = result.get("strategy_comparison")
    if strategy_comparison:
        ver_jp_sc = {"robust": "頑健", "unstable": "不安定", "overfit": "過学習",
                     "data_insufficient": "データ不足", "no_trades": "取引なし"}
        print(f"\n  戦略比較")
        print(f"  {sep2}")
        print(f"  {'戦略':<20} {'取引数':>7} {'勝率':>8} {'Sharpe':>8} {'WF判定':>10}")
        print(f"  {sep2}")
        best_sm = None
        best_sh = float('-inf')
        for sm in ["default", "trend", "contrarian"]:
            sc = strategy_comparison.get(sm)
            if sc is None:
                continue
            tc = sc["baseline"].get("trade_count", 0)
            sh = sc["baseline"].get("sharpe_ratio", 0) or 0
            if tc > 0 and sh > best_sh:
                best_sh = sh
                best_sm = sm
        for sm in ["default", "trend", "contrarian"]:
            sc = strategy_comparison.get(sm)
            if sc is None:
                continue
            b = sc["baseline"]
            wf_sc = sc["walk_forward"]
            consensus_sc = wf_sc.get("consensus", {})
            tc = b.get("trade_count", 0)
            sh = b.get("sharpe_ratio", 0.0)
            if tc <= 2:
                wr_str = "     -"
            else:
                wr_str = f"{b.get('win_rate', 0.0):>6.1f}%"
            verdict = ver_jp_sc.get(consensus_sc.get("verdict", ""), consensus_sc.get("verdict", ""))
            label = sc.get("label", sm)
            star = " ★" if sm == best_sm and tc > 0 else ""
            print(f"  {label:<20} {tc:>7} {wr_str} {sh:>8.3f} {verdict:>10}{star}")
        if best_sm and best_sh > 0:
            best_label = strategy_comparison.get(best_sm, {}).get("label", best_sm)
            print(f"  {sep2}")
            print(f"  推奨: {best_label} (Sharpe {best_sh:.3f})")
        print(f"  {sep2}")

    # Rolling window summary (A-US-001)
    rolling = wf.get("rolling_windows")
    consensus = wf.get("consensus")
    if rolling:
        print(f"\n  ローリングウォークフォワード ({len(rolling)}ウィンドウ)")
        print(f"  {sep2}")
        print(f"  {'Window':>7} {'期間終了':<12} {'訓練シャープ':>11} {'テストシャープ':>11} {'シャープ差':>9} {'過学習':>8}")
        print(f"  {sep2}")
        for rw in rolling:
            of_str = "YES" if rw["overfit_detected"] else "OK"
            print(f"  {rw['window']:>7} {rw['end_date']:<12} "
                  f"{rw['train_metrics']['sharpe_ratio']:>10.4f}  "
                  f"{rw['test_metrics']['sharpe_ratio']:>10.4f}  "
                  f"{rw['sharpe_diff_pct']:>7.1f}% {of_str:>8}")
        print(f"  {sep2}")
        cs = consensus
        ver_jp = {"robust": "頑健", "unstable": "不安定", "overfit": "過学習", "data_insufficient": "データ不足", "no_trades": "取引なし"}
        print(f"  コンセンサス: 平均シャープ {cs['mean_sharpe']:.4f} "
              f"(σ={cs['std_sharpe']:.4f})  "
              f"最大DD {cs['mean_maxdd']:.1f}% 勝率 {cs['mean_win_rate']:.1f}%  "
              f"過学習 {cs['overfit_count']}/{len(rolling)}  "
              f"判定: {ver_jp.get(cs['verdict'], cs['verdict'])}")

    print(f"\n{sep}\n")


def main():
    parser = argparse.ArgumentParser(description="Backtest engine for stock trading signals")
    parser.add_argument("--ticker", required=True, help="Ticker to backtest")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (default: 5 years ago)")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: latest trading day)")
    parser.add_argument("--tune", action="store_true", help="Run grid search parameter tuning")
    parser.add_argument("--margin", action="store_true", help="Enable margin trading (short + costs)")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--strategy", choices=["default", "trend", "contrarian", "all"],
                        default="default", help="Strategy mode for signal generation")
    parser.add_argument("--no-cache", action="store_true",
                        help="Bypass backtest result cache")
    parser.add_argument("--cache-ttl", type=int, default=86400,
                        help="Cache TTL in seconds (default: 86400 = 24h)")
    parser.add_argument("--execution-delay", action="store_true",
                        help="Apply 1-day delay between signal and execution")
    args = parser.parse_args()


    end_date = args.end
    if not end_date:
        end_date = get_latest_trading_day()

    start_date = args.start
    if not start_date:
        start_dt = pd.to_datetime(end_date) - pd.DateOffset(years=5)
        start_date = start_dt.strftime("%Y-%m-%d")

    # Check backtest result cache (must be after start_date is resolved)
    if not args.no_cache and not args.tune and args.strategy != "all":
        cached = load_cached_result(args.ticker, args.strategy,
                                    start_date, end_date,
                                    max_age=args.cache_ttl)
        if cached is not None:
            cached.pop("_config_hash", None)
            if args.output:
                output_json = json.dumps(cached, ensure_ascii=False, indent=2, default=str)
                os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
                with open(args.output, "w") as f:
                    f.write(output_json)
                print(f"Output written to {args.output} (from cache)")
            else:
                print(json.dumps(cached, ensure_ascii=False, indent=2, default=str))
            if args.summary:
                _print_summary(cached)
            return

    result = {
        "ticker": args.ticker,
        "period": {"start": start_date, "end": end_date},
        "resolved_end_date": end_date,
        "default_thresholds": DEFAULT_THRESHOLDS,
        "default_risk_params": DEFAULT_RISK_PARAMS,
    }

    # Benchmark (buy-and-hold) — pin max_date for reproducible data window
    ohlcv = load_ohlcv(args.ticker, end_date, max_date=end_date)
    result["benchmark"] = _compute_benchmark(ohlcv, start_date, end_date)

    # Baseline with default thresholds
    margin_mode = args.margin
    execution_delay = 1 if args.execution_delay else 0

    if args.strategy == "all":
        strategy_comparison = {}
        strategy_labels = {"default": "デフォルト(複合)", "trend": "トレンドフォロー", "contrarian": "逆張り"}
        for sm in ["default", "trend", "contrarian"]:
            sig_df = generate_signals(args.ticker, start_date, end_date,
                                      strategy_mode=sm)
            baseline = simulate_trades(sig_df, margin_mode=margin_mode,
                                       execution_delay=execution_delay)
            baseline["signal_census"] = compute_signal_census(sig_df, baseline["trades"])
            wf = walk_forward_rolling(args.ticker, start_date, end_date,
                                      margin_mode=margin_mode, strategy_mode=sm,
                                      execution_delay=execution_delay)
            strategy_comparison[sm] = {
                "label": strategy_labels[sm],
                "baseline": baseline,
                "walk_forward": wf,
            }
        # Use "default" as the primary result
        result["strategy_comparison"] = strategy_comparison
        sig_df = generate_signals(args.ticker, start_date, end_date)
        baseline = simulate_trades(sig_df, margin_mode=margin_mode,
                                   execution_delay=execution_delay)
        baseline["signal_census"] = compute_signal_census(sig_df, baseline["trades"])
        result["baseline"] = baseline
        wf = walk_forward_rolling(args.ticker, start_date, end_date, margin_mode=margin_mode,
                                  execution_delay=execution_delay)
        result["walk_forward"] = wf
    else:
        sig_df = generate_signals(args.ticker, start_date, end_date,
                                  strategy_mode=args.strategy)
        baseline = simulate_trades(sig_df, margin_mode=margin_mode)
        baseline["signal_census"] = compute_signal_census(sig_df, baseline["trades"])
        result["baseline"] = baseline

        # Walk-forward analysis (rolling windows)
        wf = walk_forward_rolling(args.ticker, start_date, end_date, margin_mode=margin_mode,
                                  strategy_mode=args.strategy)
        result["walk_forward"] = wf

    # Signal IC (Information Coefficient)
    ic_result = compute_signal_ic(sig_df)
    if ic_result:
        result["signal_ic"] = ic_result

    if args.tune:
        tune_result = grid_search(args.ticker, start_date, end_date, margin_mode=margin_mode)
        result["tuning"] = tune_result

        # Use best thresholds from grid search for walk-forward
        if tune_result["grid_results"]:
            best = tune_result["grid_results"][0]
            result["best_thresholds"] = best["thresholds"]
            wf_tuned = walk_forward(args.ticker, start_date, end_date, best["thresholds"], margin_mode=margin_mode)
            result["walk_forward_tuned"] = wf_tuned

    output_json = json.dumps(result, ensure_ascii=False, indent=2, default=str)

    # Save to cache (skip for --no-cache, --tune, and --strategy all)
    if not args.no_cache and not args.tune and args.strategy != "all":
        save_cached_result(args.ticker, args.strategy, start_date, end_date, result)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}")
    else:
        print(output_json)

    if args.summary:
        _print_summary(result)


if __name__ == "__main__":
    main()
