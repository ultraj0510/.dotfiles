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

from data_utils import _CUSTOM_INDICATORS, _get_stock_stats_bulk, load_ohlcv
from signal_engine import compute_trend_state, get_latest_trading_day

# Default signal thresholds
DEFAULT_THRESHOLDS = {
    "rsi_lower": 30,
    "rsi_upper": 70,
    "position_52w_lower": 25,
    "position_52w_upper": 85,
    "momentum_5d": 7.0,
    "momentum_vol": 1.0,
    "breakdown_5d": -7.0,
    "breakdown_vol": 1.5,
    "drawdown_20d": -15.0,
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


def _safe_float(val):
    if val is None or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def generate_signals(ticker: str, start_date: str, end_date: str,
                     thresholds: dict = None) -> pd.DataFrame:
    """Generate buy/sell signals for each trading day in the date range.

    Returns DataFrame with columns: date, close, high, low, rsi, 52w_position,
    5d_return, volume_ratio, boll_lb, ret_20d, atr, trend_state, sma_50,
    sma_200, ret_10d, signal (1=buy, -1=sell, 0=hold).
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

    # Signal evaluation order (documented):
    # oversold_reversal → momentum_buy → overbought → momentum_breakdown
    # → drawdown_stop → trend_following → ma_support_bounce → death_cross
    # SELL signals evaluated later, overwriting BUY within the same day.

    rows = []
    prev_date = None
    for d in dates:
        rsi = _safe_float(indicator_data["rsi"].get(d))
        pos_52w = _safe_float(indicator_data["52w_position"].get(d))
        ret_5d = _safe_float(indicator_data["5d_return"].get(d))
        vol_ratio = _safe_float(indicator_data["volume_ratio"].get(d))
        ret_20d = _safe_float(indicator_data["20d_return"].get(d))
        atr = _safe_float(indicator_data["atr"].get(d))
        sma_50 = _safe_float(indicator_data["close_50_sma"].get(d))
        sma_200 = _safe_float(indicator_data["close_200_sma"].get(d))
        ret_10d = _safe_float(indicator_data["10d_return"].get(d))
        close_val = close_map.get(d, 0)
        if isinstance(close_val, pd.Series):
            close_val = float(close_val.iloc[0]) if not close_val.empty else 0
        else:
            close_val = float(close_val) if close_val else 0
        high_val = _safe_float(high_map.get(d))
        if high_val is None:
            high_val = 0
        low_val = _safe_float(low_map.get(d))
        if low_val is None:
            low_val = 0
        boll_lb = _safe_float(indicator_data["boll_lb"].get(d))

        # Compute trend state for filter and adaptive logic
        trend_state = compute_trend_state({
            "close": close_val, "close_50_sma": sma_50,
            "close_200_sma": sma_200, "20d_return": ret_20d,
        }) if close_val and sma_50 and sma_200 else "unknown"

        signal = 0
        signal_rule = None

        # Oversold reversal BUY (with trend filter)
        if (rsi is not None and rsi < thresholds["rsi_lower"]
                and pos_52w is not None and pos_52w < thresholds["position_52w_lower"]
                and close_val > 0 and boll_lb is not None and close_val <= boll_lb * 1.02
                and trend_state != "strong_downtrend"):
            if trend_state == "downtrend":
                if rsi < 25:
                    signal = 1
                    signal_rule = "oversold_reversal"
            else:
                signal = 1
                signal_rule = "oversold_reversal"

        # Momentum BUY
        if ret_5d is not None and ret_5d > thresholds["momentum_5d"]:
            if vol_ratio is None or vol_ratio > thresholds["momentum_vol"]:
                signal = 1
                signal_rule = "momentum_buy"

        # Overbought SELL
        if (rsi is not None and rsi > thresholds["rsi_upper"]
                and pos_52w is not None and pos_52w > thresholds["position_52w_upper"]):
            signal = -1
            signal_rule = "overbought_sell"

        # Momentum breakdown SELL
        if (ret_5d is not None and ret_5d < thresholds["breakdown_5d"]
                and vol_ratio is not None and vol_ratio > thresholds["breakdown_vol"]):
            signal = -1
            signal_rule = "momentum_breakdown"

        # Drawdown stop SELL
        if ret_20d is not None and ret_20d < thresholds["drawdown_20d"]:
            signal = -1
            signal_rule = "drawdown_stop"

        # Trend following BUY
        if (sma_50 is not None and sma_200 is not None and sma_50 > sma_200
                and close_val > sma_50 and ret_10d is not None and ret_10d > 3
                and vol_ratio is not None and vol_ratio > 0.8):
            signal = 1
            signal_rule = "trend_following"

        # MA support bounce BUY
        if (sma_50 is not None and sma_200 is not None and sma_50 > sma_200
                and sma_50 * 0.98 <= close_val <= sma_50 * 1.02
                and rsi is not None and rsi < 45):
            signal = 1
            signal_rule = "ma_support_bounce"

        # Death cross SELL (exact detection via prev_date comparison)
        if (prev_date is not None
                and sma_50 is not None and sma_200 is not None):
            sma_50_prev = _safe_float(indicator_data["close_50_sma"].get(prev_date))
            sma_200_prev = _safe_float(indicator_data["close_200_sma"].get(prev_date))
            if (sma_50_prev is not None and sma_200_prev is not None
                    and sma_50_prev >= sma_200_prev
                    and sma_50 < sma_200 and close_val < sma_50):
                signal = -1
                signal_rule = "death_cross"

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
        })
        prev_date = d

    return pd.DataFrame(rows)


def _build_trade(entry_date, exit_date, entry_price, exit_price, ret,
                 exit_reason, highest_since_entry, lowest_since_entry,
                 entry_signal_rule=None):
    """Build a trade dict with computed metrics."""
    entry_dt = pd.to_datetime(entry_date)
    exit_dt = pd.to_datetime(exit_date)
    holding_days = (exit_dt - entry_dt).days
    mae_pct = (lowest_since_entry - entry_price) / entry_price * 100
    mfe_pct = (highest_since_entry - entry_price) / entry_price * 100
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
    }
    if entry_signal_rule:
        trade["entry_signal_rule"] = entry_signal_rule
    return trade


def simulate_trades(signals_df: pd.DataFrame, risk_params: dict = None) -> dict:
    """Simulate trades from signal DataFrame and compute performance metrics.

    Simple strategy: one position at a time. BUY signal enters long,
    SELL signal exits. No short selling. Uses closing prices.

    Trailing stop (ATR-based) is checked before signal processing each day.
    If triggered, the day's signal is skipped to prevent re-entry on the
    same day as a stop-out.
    """
    if risk_params is None:
        risk_params = DEFAULT_RISK_PARAMS
    atr_mult_map = risk_params["trailing_stop_atr_mult"]
    slew_max = risk_params.get("atr_slew_max", 0.5)

    if signals_df.empty:
        return _empty_metrics()

    trades = []
    in_position = False
    entry_price = 0
    entry_date = None
    entry_signal_rule = None
    highest_since_entry = 0.0
    lowest_since_entry = 0.0
    prev_effective_mult = 0.0

    daily_returns = []
    prev_close = None

    for _, row in signals_df.iterrows():
        close = row["close"]
        if close <= 0:
            continue

        if prev_close is not None and prev_close > 0:
            daily_returns.append((close - prev_close) / prev_close)
        prev_close = close

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
        if in_position:
            row_high = row.get("high", close) or close
            row_low = row.get("low", close) or close
            if row_high > highest_since_entry:
                highest_since_entry = row_high
            if row_low < lowest_since_entry:
                lowest_since_entry = row_low
            atr_val = row.get("atr")
            if atr_val is not None and not (isinstance(atr_val, float) and math.isnan(atr_val)):
                stop_level = highest_since_entry - (atr_val * effective_mult)
                if close < stop_level:
                    ret = (close - entry_price) / entry_price
                    trades.append(_build_trade(
                        entry_date, row["date"], entry_price, close, ret,
                        "trailing_stop", highest_since_entry, lowest_since_entry,
                        entry_signal_rule,
                    ))
                    in_position = False
                    entry_price = 0
                    entry_date = None
                    entry_signal_rule = None
                    highest_since_entry = 0.0
                    lowest_since_entry = 0.0
                    continue

        prev_effective_mult = effective_mult

        # Signal check
        sig = row["signal"]
        if sig == 1 and not in_position:
            in_position = True
            entry_price = close
            entry_date = row["date"]
            entry_signal_rule = row.get("signal_rule")
            highest_since_entry = close
            lowest_since_entry = close
        elif sig == -1 and in_position:
            ret = (close - entry_price) / entry_price
            trades.append(_build_trade(
                entry_date, row["date"], entry_price, close, ret,
                "signal", highest_since_entry, lowest_since_entry,
                entry_signal_rule,
            ))
            in_position = False
            entry_price = 0
            entry_date = None
            entry_signal_rule = None
            highest_since_entry = 0.0
            lowest_since_entry = 0.0

    # Close any open position at the last price
    if in_position:
        last_row = signals_df.iloc[-1]
        ret = (last_row["close"] - entry_price) / entry_price
        trades.append(_build_trade(
            entry_date, last_row["date"], entry_price, last_row["close"], ret,
            "end_of_period", highest_since_entry, lowest_since_entry,
            entry_signal_rule,
        ))

    return _compute_metrics(trades, daily_returns)


def _compute_signal_census(signals_df, trades):
    """Compute per-rule signal counts and win rates from signal_rule column and trade data."""
    signal_type = {1: "BUY", -1: "SELL"}

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
                census[rule] = {"count": 0, "type": signal_type.get(sig, "UNKNOWN"), "win_rate": 0.0}
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
        if rule in census:
            census[rule]["win_rate"] = round(rt["wins"] / rt["total"] * 100, 2)
        else:
            census[rule] = {"count": 0, "type": "UNKNOWN", "win_rate": round(rt["wins"] / rt["total"] * 100, 2)}

    census["totals"] = {"buy_count": buy_count, "sell_count": sell_count}
    return census


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
        "trades": [],
    }


def _compute_metrics(trades: list, daily_returns: list) -> dict:
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

    # Equity curve for drawdown
    equity = [1.0]
    for t in trades:
        equity.append(equity[-1] * (1 + t["return"]))
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    total_return = equity[-1] - 1.0

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
    }


def grid_search(ticker: str, start_date: str, end_date: str) -> dict:
    """Run grid search over threshold parameters."""
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
                    metrics = simulate_trades(sig_df)
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
                    })

    results.sort(key=lambda r: r["sharpe_ratio"], reverse=True)
    return {"grid_results": results, "combinations_tested": total}


def walk_forward(ticker: str, start_date: str, end_date: str,
                 thresholds: dict = None, risk_params: dict = None) -> dict:
    """Walk-forward analysis: 70% train / 30% test split.

    Train on first 70% of the period, evaluate on last 30%.
    Overfitting guard: if train/test Sharpe diff > 50% or test Sharpe < 0,
    discard tuned thresholds and use defaults.
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if risk_params is None:
        risk_params = DEFAULT_RISK_PARAMS

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    split = start + (end - start) * 0.7
    train_start = start.strftime("%Y-%m-%d")
    train_end = split.strftime("%Y-%m-%d")
    test_start = (split + timedelta(days=1)).strftime("%Y-%m-%d")
    test_end = end.strftime("%Y-%m-%d")

    # Train period
    train_sig = generate_signals(ticker, train_start, train_end, thresholds)
    train_metrics = simulate_trades(train_sig, risk_params)

    # Test period (out-of-sample)
    test_sig = generate_signals(ticker, test_start, test_end, thresholds)
    test_metrics = simulate_trades(test_sig, risk_params)

    # Overfitting guard
    train_sharpe = train_metrics["sharpe_ratio"]
    test_sharpe = test_metrics["sharpe_ratio"]
    if train_sharpe != 0:
        sharpe_diff_pct = abs((train_sharpe - test_sharpe) / train_sharpe) * 100
    else:
        sharpe_diff_pct = 0 if test_sharpe == 0 else 100

    overfit = bool((sharpe_diff_pct > 50) or (test_sharpe < 0))
    tuned_thresholds = None
    tuned_test_metrics = None
    if overfit:
        tuned_thresholds = dict(thresholds)
        tuned_test_metrics = dict(test_metrics)
        thresholds = DEFAULT_THRESHOLDS
        risk_params = DEFAULT_RISK_PARAMS
        test_sig = generate_signals(ticker, test_start, test_end, thresholds)
        test_metrics = simulate_trades(test_sig, risk_params)

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

    # Header
    print(f"\n{sep}")
    print(f"  BACKTEST SUMMARY")
    print(f"  Ticker: {result['ticker']}")
    print(f"  Period: {result['period']['start']} to {result['period']['end']}")
    print(sep)

    # Benchmark vs Strategy comparison
    print(f"\n  BENCHMARK vs STRATEGY")
    print(f"  {sep2}")
    print(f"  {'Metric':<24} {'Buy & Hold':>14} {'Strategy':>14} {'Delta':>14}")
    print(f"  {sep2}")

    rows_bm = [
        ("CAGR (%)", bm["cagr"], b["cagr"], b["cagr"] - bm["cagr"]),
        ("Max Drawdown (%)", bm["max_drawdown"], b["max_drawdown"], b["max_drawdown"] - bm["max_drawdown"]),
        ("Sharpe Ratio", bm["sharpe_ratio"], b["sharpe_ratio"], b["sharpe_ratio"] - bm["sharpe_ratio"]),
        ("Total Return (%)", bm["total_return"], b["total_return"], b["total_return"] - bm["total_return"]),
    ]
    for label, bh, st, delta in rows_bm:
        d_str = f"+{delta:.2f}" if delta > 0 else f"{delta:.2f}"
        print(f"  {label:<24} {bh:>14.2f} {st:>14.2f} {d_str:>14}")

    # Signal census
    sc = b.get("signal_census", {})
    print(f"\n  SIGNAL CENSUS")
    print(f"  {sep2}")
    totals = sc.get("totals", {})
    buy_total = totals.get("buy_count", 0)
    sell_total = totals.get("sell_count", 0)
    print(f"  Total signals: {buy_total + sell_total}  (BUY: {buy_total}, SELL: {sell_total})")
    print(f"  {sep2}")
    print(f"  {'Rule':<24} {'Type':>6} {'Count':>7} {'Win Rate':>10}")
    print(f"  {sep2}")

    for rule_name in sorted(sc):
        if rule_name == "totals":
            continue
        info = sc[rule_name]
        wr_str = f"{info['win_rate']:.1f}%" if info["count"] > 0 else "-"
        print(f"  {rule_name:<24} {info['type']:>6} {info['count']:>7} {wr_str:>10}")

    # Top 3 / Bottom 3 trades
    trades = b.get("trades", [])
    if trades:
        sorted_trades = sorted(trades, key=lambda t: t["return"], reverse=True)
        top3 = sorted_trades[:3]
        bot3 = sorted_trades[-3:]

        print(f"\n  TOP 3 TRADES")
        print(f"  {sep2}")
        print(f"  {'Entry':<12} {'Exit':<12} {'Return%':>8} {'Days':>6} {'Rule':<22} {'Reason':<14}")
        print(f"  {sep2}")
        for t in top3:
            print(f"  {t['entry_date']:<12} {t['exit_date']:<12} {t['return']*100:>7.1f}% {t['holding_days']:>5}  "
                  f"{t.get('entry_signal_rule','N/A'):<22} {t['exit_reason']:<14}")

        print(f"\n  BOTTOM 3 TRADES")
        print(f"  {sep2}")
        print(f"  {'Entry':<12} {'Exit':<12} {'Return%':>8} {'Days':>6} {'Rule':<22} {'Reason':<14}")
        print(f"  {sep2}")
        for t in reversed(bot3):
            print(f"  {t['entry_date']:<12} {t['exit_date']:<12} {t['return']*100:>7.1f}% {t['holding_days']:>5}  "
                  f"{t.get('entry_signal_rule','N/A'):<22} {t['exit_reason']:<14}")

    # Walk-forward verdict
    print(f"\n  WALK-FORWARD VERDICT")
    print(f"  {sep2}")
    overfit = wf["overfit_detected"]
    verdict = "OVERFIT DETECTED" if overfit else "PASSED"
    print(f"  Overfit: {verdict}")
    print(f"  Train Sharpe: {wf['train_metrics']['sharpe_ratio']:.4f}  |  "
          f"Test Sharpe: {wf['test_metrics']['sharpe_ratio']:.4f}")
    print(f"  Sharpe diff: {wf['sharpe_diff_pct']:.1f}%")
    if overfit:
        print(f"  Reason: ", end="")
        reasons = []
        if wf["sharpe_diff_pct"] > 50:
            reasons.append(f"train/test Sharpe divergence {wf['sharpe_diff_pct']:.1f}% > 50%")
        if wf["test_metrics"]["sharpe_ratio"] < 0:
            reasons.append(f"test Sharpe {wf['test_metrics']['sharpe_ratio']:.4f} < 0")
        print("; ".join(reasons))
        if wf.get("tuned_thresholds"):
            print(f"  Tuned thresholds discarded, using defaults")
    else:
        print(f"  No overfit detected. Tuned thresholds are reliable.")

    print(f"\n{sep}\n")


def main():
    parser = argparse.ArgumentParser(description="Backtest engine for stock trading signals")
    parser.add_argument("--ticker", required=True, help="Ticker to backtest")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (default: 1 year ago)")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: latest trading day)")
    parser.add_argument("--tune", action="store_true", help="Run grid search parameter tuning")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    args = parser.parse_args()


    end_date = args.end
    if not end_date:
        # Use latest trading day
        end_date = get_latest_trading_day()

    start_date = args.start
    if not start_date:
        start_dt = pd.to_datetime(end_date) - pd.DateOffset(years=1)
        start_date = start_dt.strftime("%Y-%m-%d")

    result = {
        "ticker": args.ticker,
        "period": {"start": start_date, "end": end_date},
        "default_thresholds": DEFAULT_THRESHOLDS,
        "default_risk_params": DEFAULT_RISK_PARAMS,
    }

    # Benchmark (buy-and-hold)
    ohlcv = load_ohlcv(args.ticker, end_date)
    result["benchmark"] = _compute_benchmark(ohlcv, start_date, end_date)

    # Baseline with default thresholds
    sig_df = generate_signals(args.ticker, start_date, end_date)
    baseline = simulate_trades(sig_df)
    baseline["signal_census"] = _compute_signal_census(sig_df, baseline["trades"])
    result["baseline"] = baseline

    # Walk-forward analysis
    wf = walk_forward(args.ticker, start_date, end_date)
    result["walk_forward"] = wf

    if args.tune:
        tune_result = grid_search(args.ticker, start_date, end_date)
        result["tuning"] = tune_result

        # Use best thresholds from grid search for walk-forward
        if tune_result["grid_results"]:
            best = tune_result["grid_results"][0]
            result["best_thresholds"] = best["thresholds"]
            wf_tuned = walk_forward(args.ticker, start_date, end_date, best["thresholds"])
            result["walk_forward_tuned"] = wf_tuned

    output_json = json.dumps(result, ensure_ascii=False, indent=2, default=str)

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
