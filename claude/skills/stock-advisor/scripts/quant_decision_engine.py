#!/usr/bin/env python3
"""Quant decision engine: deterministic trade decisions from signals + backtest + portfolio data.

Produces quant_decisions.json with per-ticker decisions combining signal assessment,
reliability vetos, position sizing, and risk limits.
"""

import argparse
import json
import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import yaml
from quant_schema import QuantDecision, ACTIONS, ORDER_TYPES
from signal_reliability import (
    shrink_win_probability,
    expected_value_after_cost_pct,
    reliability_vetoes,
)
from portfolio_optimizer import (
    compute_buy_order_shares,
    compute_sell_order_shares,
    margin_expiry_vetoes,
    position_cap_vetoes,
    MAX_POSITION_PCT,
)
from data_utils import safe_float

# --- Normalization helpers ---

_RECOMMENDATION_TO_ACTION = {
    "BUY": "BUY",
    "HOLD_BUY": "BUY",
    "HOLD": "HOLD",
    "HOLD_SELL": "REDUCE",
    "SELL": "SELL",
}


def _normalize_signal_single(raw: dict) -> dict:
    """Convert a single signal_engine result entry to flat format make_decision expects.

    Raw signal_engine entry (from results[]):
        {ticker, score: {recommendation, score}, signals: [...], indicators: {close, atr, ...}, ...}

    Returns flat dict:
        {action, current_price, atr, reduce_shares, ...}
    """
    rec = raw.get("score", {}).get("recommendation", "HOLD")
    action = _RECOMMENDATION_TO_ACTION.get(rec, "HOLD")
    indicators = raw.get("indicators", {})
    close = safe_float(indicators.get("close"))
    atr_val = safe_float(indicators.get("atr"))

    flat = {
        "action": action,
        "current_price": close or 0.0,
        "atr": atr_val or (close * 0.02 if close else 0.0),
    }

    # If signals contain a sell rule, suggest reduction
    sell_signals = [s for s in raw.get("signals", []) if s.get("type") == "SELL"]
    if sell_signals and action in ("HOLD", "BUY"):
        flat["action"] = "REDUCE"

    return flat


def _normalize_backtest(raw: dict | None) -> dict | None:
    """Convert raw backtest_engine output to flat format make_decision expects.

    Raw backtest JSON has nested structure:
        {baseline: {trade_count, win_rate, avg_win_pct, avg_loss_pct, ...},
         walk_forward: {train_metrics: {sharpe_ratio}, test_metrics: {sharpe_ratio}, consensus: {...}, overfit_detected, ...}}

    Returns flat dict:
        {total_trades, wins, losses, avg_win_pct, avg_loss_pct,
         walk_forward: {sharpe_is, sharpe_oos, verdict, ...}}
    """
    if raw is None:
        return None

    # Already flat (e.g., from test fixtures or pre-processed)
    if "total_trades" in raw or "trade_count" in raw:
        return raw

    baseline = raw.get("baseline", {})
    if not baseline:
        return None

    trade_count = baseline.get("trade_count", 0)
    win_rate = baseline.get("win_rate", 0.0)
    wins = round(trade_count * win_rate / 100) if isinstance(win_rate, (int, float)) else 0
    losses = trade_count - wins

    wf = raw.get("walk_forward", {})

    return {
        "total_trades": trade_count,
        "wins": wins,
        "losses": max(0, losses),
        "avg_win_pct": baseline.get("avg_win_pct", 0.0),
        "avg_loss_pct": baseline.get("avg_loss_pct", 0.0),
        "walk_forward": {
            "sharpe_is": wf.get("train_metrics", {}).get("sharpe_ratio"),
            "sharpe_oos": wf.get("test_metrics", {}).get("sharpe_ratio"),
            "verdict": wf.get("consensus", {}).get("verdict"),
            "sharpe_diff_pct": wf.get("sharpe_diff_pct"),
            "overfit_detected": wf.get("overfit_detected"),
            "mean_sharpe": wf.get("consensus", {}).get("mean_sharpe"),
            "std_sharpe": wf.get("consensus", {}).get("std_sharpe"),
        },
    }


# --- Argument parsing ---

def parse_args():
    p = argparse.ArgumentParser(description="Quant decision engine")
    p.add_argument("--portfolio", required=True, help="Path to portfolio.yaml")
    p.add_argument("--signals", required=True, help="Path to signals.json (signal_engine output)")
    p.add_argument("--backtest-dir", required=True, help="Directory of backtest/*.json files")
    p.add_argument("--portfolio-analytics", required=True, help="Path to portfolio_analytics.json")
    p.add_argument("-o", "--output", required=True, help="Output path for quant_decisions.json")
    return p.parse_args()


# --- Input loading ---

def load_inputs(args):
    with open(args.portfolio) as f:
        portfolio = yaml.safe_load(f)
    with open(args.signals) as f:
        signals = json.load(f)
    pa = {}
    if os.path.exists(args.portfolio_analytics):
        with open(args.portfolio_analytics) as f:
            pa = json.load(f)
    return portfolio, signals, pa


def load_backtest(backtest_dir: str, ticker: str) -> dict | None:
    """Load backtest JSON for a ticker and normalize to flat format.

    Returns normalized dict with total_trades, wins, losses, etc.
    Returns None if file not found.
    """
    path = os.path.join(backtest_dir, f"{ticker}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        raw = json.load(f)
    return _normalize_backtest(raw)


def _extract_correlation_context(portfolio_analytics: dict) -> tuple[str, list[str]]:
    """Extract correlation risk from portfolio_analytics.py output shape.

    portfolio_analytics.py writes data under a 'correlation' key.
    Returns (risk_concentration, max_correlation_pair).
    """
    correlation = portfolio_analytics.get("correlation", {})
    if not isinstance(correlation, dict):
        return "", []

    risk = correlation.get("risk_concentration", "")
    max_corr = correlation.get("max_correlation", {})
    if not isinstance(max_corr, dict):
        return risk, []

    pair = max_corr.get("pair", [])
    if not isinstance(pair, list):
        pair = []
    return risk, pair


# --- Core decision logic ---

def make_decision(
    ticker: str,
    signal_info: dict,
    backtest: dict | None,
    portfolio: dict,
    pa: dict,
) -> QuantDecision:
    """Produce a single QuantDecision for one ticker."""
    vetoes = []
    explanations = []
    account = portfolio.get("account", {})
    holdings = portfolio.get("holdings", [])

    total_assets = float(account.get("total_assets", 0))
    available_cash = float(account.get("available_cash", 0))

    # Find current holding for this ticker
    current_qty = 0
    current_value = 0.0
    cost_price = 0.0
    holding_type = "現物"
    expiry_date = None
    for h in holdings:
        if h.get("ticker") == ticker:
            current_qty += int(h.get("quantity", 0))
            current_value += float(h.get("quantity", 0)) * float(h.get("current_price", 0))
            cost_price = float(h.get("cost_price", 0))
            holding_type = h.get("position_type", "現物")
            expiry_date = h.get("expiry_date")

    # Extract signal data
    signal_action = signal_info.get("action", "HOLD")
    entry_price = float(signal_info.get("current_price", 0))
    atr = float(signal_info.get("atr", 0)) or entry_price * 0.02
    stop_loss = entry_price - atr * 2

    # --- Reliability assessment ---
    bt = backtest or {}
    trade_count = bt.get("total_trades", 0)
    win_count = bt.get("wins", 0)
    loss_count = bt.get("losses", 0)
    avg_win_pct = float(bt.get("avg_win_pct", 0))
    avg_loss_pct = float(bt.get("avg_loss_pct", 0))
    wf = bt.get("walk_forward", {})

    p_win_shrunk = shrink_win_probability(win_count, loss_count)
    ev = expected_value_after_cost_pct(
        p_win=p_win_shrunk,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        round_trip_cost_pct=0.5,
    )

    vetoes += reliability_vetoes(trade_count, p_win_shrunk, ev, wf)
    vetoes += margin_expiry_vetoes(expiry_date)
    vetoes += position_cap_vetoes(total_assets, current_value)

    # --- Correlation check ---
    corr_concentration = False
    if pa:
        risk, max_corr_pair = _extract_correlation_context(pa)
        if risk == "high":
            corr_concentration = True
        if ticker in max_corr_pair:
            corr_concentration = True

    # --- Action mapping ---
    action = signal_action

    # negative_ev blocks BUY (but not risk-reducing actions)
    if "negative_ev" in vetoes and action == "BUY":
        action = "NO_TRADE"
        explanations.append("negative EV blocks BUY")

    if "negative_walk_forward" in vetoes and action == "BUY":
        action = "NO_TRADE"
        explanations.append("negative walk-forward blocks BUY")

    # --- Confidence ---
    confidence = "moderate"
    if "low_sample" in vetoes or "overfit_walk_forward" in vetoes:
        confidence = "low"
    if ev > 1.0 and len(vetoes) == 0:
        confidence = "high"

    # --- Order sizing ---
    order_shares = 0
    target_shares = 0
    order_type = "none"
    limit_price = None

    if action == "BUY":
        if entry_price > 0 and total_assets > 0:
            target, size_vetoes = compute_buy_order_shares(
                total_assets=total_assets,
                available_cash=available_cash,
                current_position_value=current_value,
                entry_price=entry_price,
                stop_loss=stop_loss,
                atr=atr,
                correlation_concentration=corr_concentration,
            )
            vetoes += size_vetoes
            target_shares = target
            if target > 0:
                order_shares = target
                order_type = "market"
                explanations.append(f"EV={ev:.2f}%, target={target}sh")
            else:
                action = "NO_TRADE"
                order_shares = 0
                order_type = "none"

    elif action in ("SELL", "REDUCE"):
        # SELL/PARTIAL_SELL requires limit order
        if current_qty > 0:
            recommended = signal_info.get("reduce_shares", signal_info.get("order_shares", current_qty))
            order_shares = compute_sell_order_shares(current_qty, int(recommended))
            target_shares = order_shares
            order_type = "limit"
            limit_price = entry_price  # Use current price as limit
            explanations.append(f"limit sell {order_shares}sh")
        else:
            action = "NO_TRADE"
            order_type = "none"

    elif action == "HOLD":
        order_type = "none"
        explanations.append("no actionable signal")

    max_pos_val = total_assets * MAX_POSITION_PCT if total_assets > 0 else 0

    return QuantDecision(
        ticker=ticker,
        action=action,
        confidence=confidence,
        expected_value_after_cost_pct=round(ev, 4),
        p_win_shrunk=round(p_win_shrunk, 4) if p_win_shrunk else None,
        avg_win_pct=round(avg_win_pct, 4) if avg_win_pct else None,
        avg_loss_pct=round(avg_loss_pct, 4) if avg_loss_pct else None,
        max_position_value=round(max_pos_val, 2),
        target_shares=target_shares,
        order_shares=order_shares,
        order_type=order_type,
        limit_price=limit_price,
        vetoes=vetoes,
        explanations=explanations,
    )


def main():
    args = parse_args()
    portfolio, signals, pa = load_inputs(args)

    # Get unique tickers from portfolio holdings
    holdings = portfolio.get("holdings", [])
    tickers = sorted(set(h["ticker"] for h in holdings))

    # Normalize signals from signal_engine output format
    if isinstance(signals, dict):
        # Raw signal_engine format: {"results": [...], "generated_at": ..., "reference_date": ...}
        if "results" in signals and isinstance(signals["results"], list):
            signal_map = {}
            for res in signals["results"]:
                t = res.get("ticker", "")
                if t:
                    signal_map[t] = _normalize_signal_single(res)
            # Add any tickers from signals not in portfolio
            tickers = sorted(set(tickers) | set(signal_map.keys()))
        # Pre-processed format: {"tickers": {"7203.T": {...}}}
        elif "tickers" in signals:
            signal_map = signals["tickers"]
            tickers = sorted(set(tickers) | set(signal_map.keys()))
        # Single result by ticker
        else:
            signal_map = signals
    elif isinstance(signals, list):
        # List format: [{"ticker": "7203.T", "action": "BUY", ...}]
        signal_map = {}
        for s in signals:
            t = s.get("ticker", "")
            if t:
                signal_map[t] = s
                if t not in tickers:
                    tickers.append(t)
        tickers = sorted(tickers)
    else:
        signal_map = {}

    decisions = []
    for ticker in tickers:
        signal_info = signal_map.get(ticker, {})
        bt = load_backtest(args.backtest_dir, ticker)
        decision = make_decision(ticker, signal_info, bt, portfolio, pa)
        decisions.append(decision)

    # Serialize
    output = {
        "generated_at": None,  # caller fills if desired
        "decisions": [
            {
                "ticker": d.ticker,
                "action": d.action,
                "confidence": d.confidence,
                "expected_value_after_cost_pct": d.expected_value_after_cost_pct,
                "p_win_shrunk": d.p_win_shrunk,
                "avg_win_pct": d.avg_win_pct,
                "avg_loss_pct": d.avg_loss_pct,
                "max_position_value": d.max_position_value,
                "target_shares": d.target_shares,
                "order_shares": d.order_shares,
                "order_type": d.order_type,
                "limit_price": d.limit_price,
                "vetoes": d.vetoes,
                "explanations": d.explanations,
            }
            for d in decisions
        ],
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(decisions)} decisions to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
