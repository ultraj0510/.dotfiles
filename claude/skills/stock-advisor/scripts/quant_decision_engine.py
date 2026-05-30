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
from quant_schema import QuantDecision, PositionDecision, ACTIONS, ORDER_TYPES
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
from strategy_review import classify_strategy_posture

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

    raw_signals = raw.get("signals", [])
    buy_signals = [s for s in raw_signals if s.get("type") == "BUY"]
    sell_signals = [s for s in raw_signals if s.get("type") == "SELL"]
    strong_sell_rules = {
        s.get("rule")
        for s in sell_signals
        if s.get("strength") == "strong" or s.get("rule") in {"drawdown_stop", "momentum_breakdown"}
    }

    flat["signals"] = raw_signals
    flat["indicators"] = indicators
    flat["trend_state"] = raw.get("trend_state", "")
    flat["buy_signal_count"] = len(buy_signals)
    flat["sell_signal_count"] = len(sell_signals)
    flat["strong_sell_rules"] = sorted(strong_sell_rules)

    if rec == "HOLD_SELL" or strong_sell_rules:
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

    normalized = {
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

    # Preserve strategy gate metadata when present
    if "strategy_selection" in raw:
        normalized["strategy_selection"] = raw["strategy_selection"]
    if "benchmark_comparison" in raw:
        normalized["benchmark_comparison"] = raw["benchmark_comparison"]

    return normalized


# --- Argument parsing ---

def parse_args():
    p = argparse.ArgumentParser(description="Quant decision engine")
    p.add_argument("--portfolio", required=True, help="Path to portfolio.yaml")
    p.add_argument("--signals", required=True, help="Path to signals.json (signal_engine output)")
    p.add_argument("--backtest-dir", required=True, help="Directory of backtest/*.json files")
    p.add_argument("--portfolio-analytics", required=True, help="Path to portfolio_analytics.json")
    p.add_argument("-o", "--output", required=True, help="Output path for quant_decisions.json")
    p.add_argument("--strategy-risk-mode", choices=["defensive", "balanced", "aggressive"],
                   default="balanced", help="Risk mode for candidate strategy execution")
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


def _held_positions(portfolio: dict, ticker: str) -> list[dict]:
    """Return normalized position dicts for all lots of a ticker."""
    positions = []
    for index, holding in enumerate(portfolio.get("holdings", []), start=1):
        if holding.get("ticker") != ticker:
            continue
        current = float(holding.get("current_price", 0))
        cost = float(holding.get("cost_price", 0))
        pnl_pct = ((current - cost) / cost * 100) if cost > 0 else None
        positions.append({
            **holding,
            "position_id": f'{ticker}:{holding.get("position_type", "現物")}:{index}',
            "unrealized_pnl_pct": pnl_pct,
        })
    return positions


def _rank_reduce_positions(positions: list[dict]) -> list[dict]:
    """Sort positions for reduction: margin first, then earliest expiry, then worst P&L."""
    return sorted(
        positions,
        key=lambda p: (
            0 if p.get("position_type") == "信用" else 1,
            p.get("expiry_date") or "9999-12-31",
            p.get("unrealized_pnl_pct") if p.get("unrealized_pnl_pct") is not None else 0,
        ),
    )


def _allocate_reduce_to_positions(
    total_shares: int, positions: list[dict],
) -> list[dict]:
    """Allocate reduce shares across ranked positions."""
    allocations = []
    remaining = total_shares
    for pos in _rank_reduce_positions(positions):
        take = min(remaining, pos.get("quantity", 0))
        take = (take // 100) * 100  # lot-aligned
        if take > 0:
            allocations.append({**pos, "allocated": take})
            remaining -= take
        if remaining < 100:
            break
    return allocations


def _position_metrics(total_assets: float, positions: list[dict]) -> dict:
    current_value = sum(float(p.get("quantity", 0)) * float(p.get("current_price", 0)) for p in positions)
    cost_basis = sum(float(p.get("quantity", 0)) * float(p.get("cost_price", 0)) for p in positions)
    unrealized_pnl_pct = ((current_value - cost_basis) / cost_basis * 100) if cost_basis > 0 else None
    return {
        "current_value": current_value,
        "cost_basis": cost_basis,
        "portfolio_weight_pct": round(current_value / total_assets * 100, 2) if total_assets > 0 else None,
        "cost_basis_weight_pct": round(cost_basis / total_assets * 100, 2) if total_assets > 0 else None,
        "unrealized_pnl_pct": round(unrealized_pnl_pct, 2) if unrealized_pnl_pct is not None else None,
        "downside_10pct_yen": int(round(current_value * 0.10)),
    }


def _indicator_float(signal_info: dict, key: str) -> float | None:
    value = signal_info.get("indicators", {}).get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _protective_stop_price(signal_info: dict, entry_price: float, atr: float) -> float | None:
    ema10 = _indicator_float(signal_info, "close_10_ema")
    if ema10 and ema10 > 0:
        return round(ema10, 2)
    if entry_price > 0 and atr > 0:
        return round(entry_price - atr * 2, 2)
    return None


CONFIDENCE_CAPPING_RISK_FLAGS = {
    "negative_walk_forward",
    "overfit_walk_forward",
    "low_sample",
    "position_over_cap_watch",
    "position_over_cap_loss_concentration",
    "correlation_concentration",
}


def _has_confidence_capping_risk(risk_flags: list[str]) -> bool:
    return any(flag in CONFIDENCE_CAPPING_RISK_FLAGS for flag in risk_flags)


def _range_rebalance_plan(signal_info: dict, current_qty: int, portfolio_weight_pct: float | None) -> dict:
    indicators = signal_info.get("indicators", {})
    current_price = _indicator_float(signal_info, "close") or float(signal_info.get("current_price", 0))
    boll_mid = _indicator_float(signal_info, "boll")
    boll_lb = _indicator_float(signal_info, "boll_lb")
    atr = float(signal_info.get("atr", 0) or 0)

    trim_shares = max(100, (current_qty // 10 // 100) * 100)
    trim_shares = min(trim_shares, 300)

    trim_trigger = boll_mid or current_price
    reentry_watch = boll_lb or (current_price - atr if atr else current_price * 0.95)

    return {
        "mode": "trim_on_rebound_rebuy_on_pullback",
        "trim_shares": trim_shares,
        "trim_trigger_price": round(trim_trigger, 2),
        "reentry_watch_price": round(reentry_watch, 2),
        "max_reentry_shares": trim_shares,
        "reentry_allowed_after_trim": True,
        "reentry_requires": [
            "trim_filled",
            "price_near_lower_band",
            "rsi_below_40_or_reversal_signal",
        ],
    }


# --- Core decision logic ---

def make_decision(
    ticker: str,
    signal_info: dict,
    backtest: dict | None,
    portfolio: dict,
    pa: dict,
    strategy_risk_mode: str = "balanced",
) -> QuantDecision:
    """Produce a single QuantDecision for one ticker."""
    vetoes = []
    risk_flags = []
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
    positions = _held_positions(portfolio, ticker)
    metrics = _position_metrics(total_assets, positions)

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

    raw_reliability_flags = reliability_vetoes(trade_count, p_win_shrunk, ev, wf)
    margin_flags = margin_expiry_vetoes(expiry_date)

    # Classify: BUY-blocking flags go to vetoes; others are risk_flags
    buy_blocking_flags = {"negative_ev", "negative_walk_forward", "low_sample", "overfit_walk_forward"}
    if signal_action == "BUY":
        vetoes += [flag for flag in raw_reliability_flags if flag in buy_blocking_flags]
        risk_flags += [flag for flag in raw_reliability_flags if flag not in buy_blocking_flags]
    else:
        risk_flags += raw_reliability_flags

    vetoes += margin_flags
    risk_posture = "neutral"
    protective_stop = None
    advisory_plan = {}
    portfolio_weight_pct = metrics["portfolio_weight_pct"]
    unrealized_pnl_pct = metrics["unrealized_pnl_pct"]

    if portfolio_weight_pct is not None and portfolio_weight_pct > MAX_POSITION_PCT * 100:
        if unrealized_pnl_pct is not None and unrealized_pnl_pct >= 50:
            risk_posture = "protect_profit"
            protective_stop = _protective_stop_price(signal_info, entry_price, atr)
            advisory_plan = {
                "mode": "trail_stop",
                "stop_source": "close_10_ema_or_2atr",
                "sell_only_if_stop_breaks": True,
            }
            risk_flags.append("position_over_cap_watch")
        elif unrealized_pnl_pct is not None and unrealized_pnl_pct < 0:
            risk_posture = "rebalance_on_strength"
            advisory_plan = _range_rebalance_plan(signal_info, current_qty, portfolio_weight_pct)
            risk_flags.append("position_over_cap_loss_concentration")
        else:
            risk_flags.append("position_over_cap_watch")

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
    elif "low_sample" in risk_flags or "overfit_walk_forward" in risk_flags:
        confidence = "low"
    elif ev > 1.0 and len(vetoes) == 0 and not _has_confidence_capping_risk(risk_flags):
        confidence = "high"

    # --- Order sizing ---
    pos_decisions = []
    order_shares = 0
    target_shares = 0
    order_type = "none"
    limit_price = None

    if current_qty == 100 and risk_posture == "protect_profit" and not signal_info.get("strong_sell_rules"):
        if action == "REDUCE":
            action = "HOLD"
            explanations.append("single-lot winner protected; use trailing stop instead of full exit")
        vetoes.append("single_lot_full_exit_guard")

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
        # REDUCE/SELL: allocate across positions (margin first, then worst P&L)
        positions = _held_positions(portfolio, ticker)
        if positions and current_qty > 0:
            recommended = signal_info.get("reduce_shares", signal_info.get("order_shares", current_qty))
            base_shares = compute_sell_order_shares(current_qty, int(recommended))
            target_shares = base_shares
            order_shares = base_shares
            order_type = "limit"
            limit_price = entry_price

            # Allocate across positions
            allocs = _allocate_reduce_to_positions(base_shares, positions)
            for a in allocs:
                pos = PositionDecision(
                    position_id=a["position_id"],
                    ticker=ticker,
                    position_type=a.get("position_type", "現物"),
                    action=action,
                    quantity=a.get("quantity", 0),
                    order_shares=a["allocated"],
                    reason=vetoes[-1] if vetoes else "",
                    expiry_date=a.get("expiry_date"),
                    unrealized_pnl_pct=a.get("unrealized_pnl_pct"),
                )
                pos_decisions.append(pos)
            explanations.append(f"limit sell {order_shares}sh across {len(allocs)} positions")
        else:
            action = "NO_TRADE"
            order_type = "none"
            order_type = "none"

    elif action == "HOLD":
        order_type = "none"
        explanations.append("no actionable signal")

    max_pos_val = total_assets * MAX_POSITION_PCT if total_assets > 0 else 0

    # Strategy policy: validated strategies trade normally; candidate strategies trade smaller.
    # Only apply when backtest has strategy gate data (strategy_selection or benchmark_comparison).
    if bt and (bt.get("strategy_selection") or bt.get("benchmark_comparison")):
        bt_for_policy = dict(bt)
        bt_for_policy["risk_posture"] = risk_posture
        bt_for_policy["expected_value_after_cost_pct"] = ev
        posture = classify_strategy_posture(bt_for_policy, risk_mode=strategy_risk_mode)
        posture_name = posture["posture"]
        size_multiplier = posture["size_multiplier"]

        if posture_name == "candidate_strategy" and size_multiplier > 0:
            if "candidate_strategy_reduced_size" not in risk_flags:
                risk_flags.append("candidate_strategy_reduced_size")
            if action in ("BUY", "SELL", "REDUCE") and order_shares > 0:
                reduced_shares = int(order_shares * size_multiplier)
                reduced_shares = (reduced_shares // 100) * 100
                if reduced_shares <= 0 and order_shares >= 100:
                    reduced_shares = 100
                order_shares = min(order_shares, reduced_shares)
                target_shares = min(target_shares, order_shares) if target_shares else target_shares
                explanations.append(f"candidate strategy reduced size: {size_multiplier:.2f}x")

        elif posture_name in ("hold_baseline", "profit_protection"):
            if posture_name == "hold_baseline" and "strategy_not_tradeable" not in risk_flags:
                risk_flags.append("strategy_not_tradeable")
            has_margin_urgency = any(v.startswith("margin_expiry_") for v in vetoes)
            if action in ("BUY", "SELL", "REDUCE") and not has_margin_urgency:
                action = "HOLD"
                order_shares = 0
                target_shares = 0
                order_type = "none"
                explanations.append("technical signal blocked: strategy not tradeable")

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
        position_decisions=pos_decisions,
        risk_posture=risk_posture,
        protective_stop_price=protective_stop,
        portfolio_weight_pct=metrics["portfolio_weight_pct"],
        cost_basis_weight_pct=metrics["cost_basis_weight_pct"],
        unrealized_pnl_pct=metrics["unrealized_pnl_pct"],
        downside_10pct_yen=metrics["downside_10pct_yen"],
        advisory_plan=advisory_plan,
        vetoes=vetoes,
        risk_flags=risk_flags,
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
        decision = make_decision(ticker, signal_info, bt, portfolio, pa,
                                 strategy_risk_mode=args.strategy_risk_mode)
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
                "risk_posture": d.risk_posture,
                "protective_stop_price": d.protective_stop_price,
                "portfolio_weight_pct": d.portfolio_weight_pct,
                "cost_basis_weight_pct": d.cost_basis_weight_pct,
                "unrealized_pnl_pct": d.unrealized_pnl_pct,
                "downside_10pct_yen": d.downside_10pct_yen,
                "advisory_plan": d.advisory_plan,
                "position_decisions": [
                    {
                        "position_id": pd.position_id,
                        "position_type": pd.position_type,
                        "action": pd.action,
                        "quantity": pd.quantity,
                        "order_shares": pd.order_shares,
                        "reason": pd.reason,
                        "expiry_date": pd.expiry_date,
                        "unrealized_pnl_pct": pd.unrealized_pnl_pct,
                    }
                    for pd in d.position_decisions
                ],
                "vetoes": d.vetoes,
                "risk_flags": d.risk_flags,
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
