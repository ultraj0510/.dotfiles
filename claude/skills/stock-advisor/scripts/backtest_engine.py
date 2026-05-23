#!/usr/bin/env python3
"""Walk-forward backtest engine for rule-based stock trading signals.

Usage:
    python backtest_engine.py --ticker 1515.T
    python backtest_engine.py --ticker 1515.T --tune
    python backtest_engine.py --ticker 1515.T --start 2024-01-01 --end 2025-01-01
"""

import argparse
import json
import math
import os
from datetime import timedelta

import numpy as np
import pandas as pd

from data_utils import _CUSTOM_INDICATORS, _get_stock_stats_bulk, load_ohlcv

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

    Returns DataFrame with columns: date, close, rsi, 52w_position, 5d_return,
    volume_ratio, boll_lb, signal (1=buy, -1=sell, 0=hold).
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    # Build indicator DataFrame from bulk data
    indicator_data = {}
    for ind in ALL_INDICATORS:
        bulk = _get_stock_stats_bulk(ticker, ind, end_date)
        indicator_data[ind] = bulk

    # Get close prices from OHLCV
    ohlcv = load_ohlcv(ticker, end_date)
    ohlcv["date_str"] = ohlcv["Date"].dt.strftime("%Y-%m-%d")
    close_map = dict(zip(ohlcv["date_str"], ohlcv["Close"]))

    # Get all dates from any indicator
    all_dates = set()
    for ind_data in indicator_data.values():
        all_dates.update(ind_data.keys())
    dates = sorted(all_dates)

    # Filter to range
    dates = [d for d in dates if start_date <= d <= end_date]

    rows = []
    for d in dates:
        rsi = _safe_float(indicator_data["rsi"].get(d))
        pos_52w = _safe_float(indicator_data["52w_position"].get(d))
        ret_5d = _safe_float(indicator_data["5d_return"].get(d))
        vol_ratio = _safe_float(indicator_data["volume_ratio"].get(d))
        close_val = close_map.get(d, 0)
        if isinstance(close_val, pd.Series):
            close_val = float(close_val.iloc[0]) if not close_val.empty else 0
        else:
            close_val = float(close_val) if close_val else 0
        boll_lb = _safe_float(indicator_data["boll_lb"].get(d))

        signal = 0

        # Oversold reversal BUY
        if (rsi is not None and rsi < thresholds["rsi_lower"]
                and pos_52w is not None and pos_52w < thresholds["position_52w_lower"]
                and close_val > 0 and boll_lb is not None and close_val <= boll_lb * 1.02):
            signal = 1

        # Momentum BUY
        if ret_5d is not None and ret_5d > thresholds["momentum_5d"]:
            if vol_ratio is None or vol_ratio > thresholds["momentum_vol"]:
                signal = 1

        # Overbought SELL
        if (rsi is not None and rsi > thresholds["rsi_upper"]
                and pos_52w is not None and pos_52w > thresholds["position_52w_upper"]):
            signal = -1

        # Momentum breakdown SELL
        if (ret_5d is not None and ret_5d < thresholds["breakdown_5d"]
                and vol_ratio is not None and vol_ratio > thresholds["breakdown_vol"]):
            signal = -1

        rows.append({
            "date": d,
            "close": close_val,
            "rsi": rsi,
            "52w_position": pos_52w,
            "5d_return": ret_5d,
            "volume_ratio": vol_ratio,
            "boll_lb": boll_lb,
            "signal": signal,
        })

    return pd.DataFrame(rows)


def simulate_trades(signals_df: pd.DataFrame) -> dict:
    """Simulate trades from signal DataFrame and compute performance metrics.

    Simple strategy: one position at a time. BUY signal enters long,
    SELL signal exits. No short selling. Uses closing prices.
    """
    if signals_df.empty:
        return _empty_metrics()

    trades = []
    in_position = False
    entry_price = 0
    entry_date = None

    # Track daily returns for Sharpe/Sortino
    daily_returns = []
    prev_close = None

    for _, row in signals_df.iterrows():
        close = row["close"]
        if close <= 0:
            continue

        if prev_close is not None and prev_close > 0:
            daily_returns.append((close - prev_close) / prev_close)
        prev_close = close

        sig = row["signal"]
        if sig == 1 and not in_position:
            in_position = True
            entry_price = close
            entry_date = row["date"]
        elif sig == -1 and in_position:
            ret = (close - entry_price) / entry_price
            trades.append({
                "entry_date": entry_date,
                "exit_date": row["date"],
                "entry_price": entry_price,
                "exit_price": close,
                "return": ret,
            })
            in_position = False
            entry_price = 0
            entry_date = None

    # Close any open position at the last price
    if in_position:
        last_row = signals_df.iloc[-1]
        ret = (last_row["close"] - entry_price) / entry_price
        trades.append({
            "entry_date": entry_date,
            "exit_date": last_row["date"],
            "entry_price": entry_price,
            "exit_price": last_row["close"],
            "return": ret,
        })

    return _compute_metrics(trades, daily_returns)


def _empty_metrics():
    return {
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "cagr": 0.0,
        "total_return": 0.0,
        "trade_count": 0,
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
                 thresholds: dict = None) -> dict:
    """Walk-forward analysis: 70% train / 30% test split.

    Train on first 70% of the period, evaluate on last 30%.
    Overfitting guard: if train/test Sharpe diff > 50% or test Sharpe < 0,
    discard tuned thresholds and use defaults.
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    split = start + (end - start) * 0.7
    train_start = start.strftime("%Y-%m-%d")
    train_end = split.strftime("%Y-%m-%d")
    test_start = (split + timedelta(days=1)).strftime("%Y-%m-%d")
    test_end = end.strftime("%Y-%m-%d")

    # Train period
    train_sig = generate_signals(ticker, train_start, train_end, thresholds)
    train_metrics = simulate_trades(train_sig)

    # Test period (out-of-sample)
    test_sig = generate_signals(ticker, test_start, test_end, thresholds)
    test_metrics = simulate_trades(test_sig)

    # Overfitting guard
    train_sharpe = train_metrics["sharpe_ratio"]
    test_sharpe = test_metrics["sharpe_ratio"]
    if train_sharpe != 0:
        sharpe_diff_pct = abs((train_sharpe - test_sharpe) / train_sharpe) * 100
    else:
        sharpe_diff_pct = 0 if test_sharpe == 0 else 100

    overfit = bool((sharpe_diff_pct > 50) or (test_sharpe < 0))
    if overfit:
        thresholds = DEFAULT_THRESHOLDS
        test_sig = generate_signals(ticker, test_start, test_end, thresholds)
        test_metrics = simulate_trades(test_sig)

    return {
        "train_period": {"start": train_start, "end": train_end},
        "test_period": {"start": test_start, "end": test_end},
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "sharpe_diff_pct": round(sharpe_diff_pct, 2),
        "overfit_detected": overfit,
        "thresholds_used": thresholds,
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest engine for stock trading signals")
    parser.add_argument("--ticker", required=True, help="Ticker to backtest")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (default: 1 year ago)")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: latest trading day)")
    parser.add_argument("--tune", action="store_true", help="Run grid search parameter tuning")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    args = parser.parse_args()

    end_date = args.end
    if not end_date:
        # Use latest trading day
        from signal_engine import get_latest_trading_day
        end_date = get_latest_trading_day()

    start_date = args.start
    if not start_date:
        start_dt = pd.to_datetime(end_date) - pd.DateOffset(years=1)
        start_date = start_dt.strftime("%Y-%m-%d")

    result = {
        "ticker": args.ticker,
        "period": {"start": start_date, "end": end_date},
        "default_thresholds": DEFAULT_THRESHOLDS,
    }

    # Baseline with default thresholds
    sig_df = generate_signals(args.ticker, start_date, end_date)
    baseline = simulate_trades(sig_df)
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


if __name__ == "__main__":
    main()
