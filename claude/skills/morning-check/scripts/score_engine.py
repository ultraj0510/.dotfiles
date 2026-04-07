"""
score_engine.py — Signal scoring, macro adjustment, and CSV I/O for morning-check.
"""

import csv
import os
from datetime import date

# ── Default strategy ──────────────────────────────────────────────────────────

DEFAULT_STRATEGY = {
    "version": 1,
    "signals": {
        "rsi_oversold":    {"score": 20,  "threshold": 35},
        "rsi_overbought":  {"score": -20, "threshold": 68},
        "bb_lower_touch":  {"score": 15,  "threshold": 0.02},
        "bb_upper_touch":  {"score": -15, "threshold": 0.02},
        "w52_low":         {"score": 10,  "threshold": 15},
        "w52_high":        {"score": -10, "threshold": 85},
        "momentum_surge":  {"score": 12,  "threshold": 7.0},
        "analyst_upside":  {"score": 15,  "threshold": 25},
        "analyst_downside":{"score": -15, "threshold": -15},
        "short_squeeze":   {"score": 8,   "threshold": 10},
        "pnl_loss":        {"score": -25, "threshold": -15},
        "pnl_profit":      {"score": 20,  "threshold": 30},
    },
    "macro_multipliers": {
        "vix_risk_off":  {"multiplier": 0.6, "threshold": 25},
        "vix_risk_on":   {"multiplier": 1.2, "threshold": 13},
        "sp500_down":    {"multiplier": 0.7, "threshold": -1.5},
        "sp500_up":      {"multiplier": 1.1, "threshold": 1.0},
        "usdjpy_strong": {"multiplier": 1.1, "threshold": 155},
        "usdjpy_weak":   {"multiplier": 0.9, "threshold": 140},
    },
    "action_thresholds": {"buy": 25, "sell": -25, "action_flag": 15},
}

# ── CSV field definitions ─────────────────────────────────────────────────────

DAILY_SCORES_FIELDS = [
    "date", "ticker", "position_type", "raw_score", "adjusted_score",
    "macro_multiplier", "signals_fired", "current_price", "rsi",
    "bb_pos", "w52_pos", "action_flag",
]

TRADE_LOG_FIELDS = [
    "date", "ticker", "action", "quantity", "price", "position_type",
    "cost_price", "score_at_entry", "signals_at_entry",
    "exit_date", "exit_price", "exit_quantity", "pnl_pct", "pnl_jpy",
]

# ── load_strategy ─────────────────────────────────────────────────────────────

def load_strategy(strategy_path: str) -> dict:
    """Load strategy from YAML file; fall back to DEFAULT_STRATEGY on any error."""
    try:
        import yaml
        with open(strategy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict):
            return data
    except Exception:
        pass
    return DEFAULT_STRATEGY


# ── compute_macro_multiplier ──────────────────────────────────────────────────

def compute_macro_multiplier(macro: dict, strategy: dict) -> float:
    """
    Compute the product of all applicable macro multipliers.

    VIX, S&P500, USD/JPY conditions are mutually exclusive within each pair.
    """
    mm = strategy.get("macro_multipliers", {})
    result = 1.0

    # VIX
    vix = macro.get("^VIX", {}).get("latest")
    if vix is not None:
        risk_off = mm.get("vix_risk_off", {})
        risk_on  = mm.get("vix_risk_on",  {})
        if risk_off and vix >= risk_off["threshold"]:
            result *= risk_off["multiplier"]
        elif risk_on and vix <= risk_on["threshold"]:
            result *= risk_on["multiplier"]

    # S&P 500 (1-day change %)
    sp500_chg = macro.get("^GSPC", {}).get("change_1d")
    if sp500_chg is not None:
        sp_down = mm.get("sp500_down", {})
        sp_up   = mm.get("sp500_up",   {})
        if sp_down and sp500_chg <= sp_down["threshold"]:
            result *= sp_down["multiplier"]
        elif sp_up and sp500_chg >= sp_up["threshold"]:
            result *= sp_up["multiplier"]

    # USD/JPY
    usdjpy = macro.get("USDJPY=X", {}).get("latest")
    if usdjpy is not None:
        strong = mm.get("usdjpy_strong", {})
        weak   = mm.get("usdjpy_weak",   {})
        if strong and usdjpy >= strong["threshold"]:
            result *= strong["multiplier"]
        elif weak and usdjpy <= weak["threshold"]:
            result *= weak["multiplier"]

    return round(result, 4)


# ── score_holding ─────────────────────────────────────────────────────────────

def score_holding(holding, metrics, analyst, macro, strategy) -> dict:
    """Score a single holding and return scoring details."""
    empty_result = {
        "raw_score": 0,
        "adjusted_score": 0.0,
        "macro_multiplier": 1.0,
        "signals_fired": [],
        "action_flag": False,
    }

    if not metrics:
        return empty_result

    signals = strategy.get("signals", {})
    current    = metrics.get("current")
    cost_price = holding.get("cost_price")

    signals_fired = []
    positive_score = 0
    negative_score = 0

    def _fire(name, score):
        nonlocal positive_score, negative_score
        signals_fired.append(name)
        if score > 0:
            positive_score += score
        else:
            negative_score += score

    # rsi_oversold
    cfg = signals.get("rsi_oversold", {})
    if cfg and metrics.get("rsi") is not None:
        if metrics["rsi"] <= cfg["threshold"]:
            _fire("rsi_oversold", cfg["score"])

    # rsi_overbought
    cfg = signals.get("rsi_overbought", {})
    if cfg and metrics.get("rsi") is not None:
        if metrics["rsi"] >= cfg["threshold"]:
            _fire("rsi_overbought", cfg["score"])

    # bb_lower_touch: price is near (but not far below) the lower band
    # 0 <= (current - bb_lower) / bb_lower <= threshold
    cfg = signals.get("bb_lower_touch", {})
    if cfg and current is not None and metrics.get("bb_lower") is not None:
        bb_lower = metrics["bb_lower"]
        if bb_lower is not None:
            ratio = (current - bb_lower) / bb_lower
            if 0 <= ratio <= cfg["threshold"]:
                _fire("bb_lower_touch", cfg["score"])

    # bb_upper_touch: price is near (but not far above) the upper band
    # 0 <= (bb_upper - current) / bb_upper <= threshold
    cfg = signals.get("bb_upper_touch", {})
    if cfg and current is not None and metrics.get("bb_upper") is not None:
        bb_upper = metrics["bb_upper"]
        if bb_upper is not None:
            ratio = (bb_upper - current) / bb_upper
            if 0 <= ratio <= cfg["threshold"]:
                _fire("bb_upper_touch", cfg["score"])

    # w52_low
    cfg = signals.get("w52_low", {})
    if cfg and metrics.get("pos_52w") is not None:
        if metrics["pos_52w"] <= cfg["threshold"]:
            _fire("w52_low", cfg["score"])

    # w52_high
    cfg = signals.get("w52_high", {})
    if cfg and metrics.get("pos_52w") is not None:
        if metrics["pos_52w"] >= cfg["threshold"]:
            _fire("w52_high", cfg["score"])

    # momentum_surge
    cfg = signals.get("momentum_surge", {})
    if cfg and metrics.get("ret_5d") is not None:
        if metrics["ret_5d"] >= cfg["threshold"]:
            _fire("momentum_surge", cfg["score"])

    # analyst_upside / analyst_downside
    target_mean = analyst.get("target_mean") if analyst else None
    if target_mean is not None and current:
        upside_pct = (target_mean / current - 1) * 100

        cfg = signals.get("analyst_upside", {})
        if cfg and upside_pct >= cfg["threshold"]:
            _fire("analyst_upside", cfg["score"])

        cfg = signals.get("analyst_downside", {})
        if cfg and upside_pct <= cfg["threshold"]:
            _fire("analyst_downside", cfg["score"])

    # short_squeeze
    cfg = signals.get("short_squeeze", {})
    short_pct = analyst.get("short_pct") if analyst else None
    if cfg and short_pct is not None:
        if short_pct >= cfg["threshold"]:
            _fire("short_squeeze", cfg["score"])

    # pnl_loss / pnl_profit
    if current is not None and cost_price:
        pnl_pct = (current / cost_price - 1) * 100

        cfg = signals.get("pnl_loss", {})
        if cfg and pnl_pct <= cfg["threshold"]:
            _fire("pnl_loss", cfg["score"])

        cfg = signals.get("pnl_profit", {})
        if cfg and pnl_pct >= cfg["threshold"]:
            _fire("pnl_profit", cfg["score"])

    raw_score = positive_score + negative_score
    macro_mult = compute_macro_multiplier(macro, strategy)
    adjusted_score = round(positive_score * macro_mult + negative_score, 2)

    # action_flag
    action_threshold = strategy.get("action_thresholds", {}).get("action_flag", 15)
    action_flag = abs(adjusted_score) >= action_threshold

    # Force action_flag for 信用 positions expiring within 60 days
    if not action_flag:
        if holding.get("position_type") == "信用" and holding.get("expiry_date"):
            try:
                expiry = date.fromisoformat(holding["expiry_date"])
                days_until = (expiry - date.today()).days
                if days_until < 60:
                    action_flag = True
            except (ValueError, TypeError):
                pass

    return {
        "raw_score": raw_score,
        "adjusted_score": adjusted_score,
        "macro_multiplier": macro_mult,
        "signals_fired": signals_fired,
        "action_flag": action_flag,
    }


# ── CSV I/O ───────────────────────────────────────────────────────────────────

def _daily_scores_path(data_dir: str) -> str:
    return os.path.join(data_dir, "daily_scores.csv")


def _trade_log_path(data_dir: str) -> str:
    return os.path.join(data_dir, "trade_log.csv")


def append_daily_scores(holdings_scores: list, data_dir: str) -> None:
    """Append scoring rows to daily_scores.csv, creating with header if needed."""
    os.makedirs(data_dir, exist_ok=True)
    path = _daily_scores_path(data_dir)
    file_exists = os.path.isfile(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DAILY_SCORES_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for row in holdings_scores:
            writer.writerow(row)


def read_latest_score(ticker: str, position_type: str, data_dir: str):
    """Return the last daily_scores row matching ticker + position_type, or None."""
    path = _daily_scores_path(data_dir)
    if not os.path.isfile(path):
        return None
    last_match = None
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker") == ticker and row.get("position_type") == position_type:
                last_match = row
    return last_match


def record_trade_entry(date, ticker, action, qty, price, position_type,
                       cost_price, score_data, data_dir) -> None:
    """Append a BUY/SELL entry row to trade_log.csv."""
    os.makedirs(data_dir, exist_ok=True)
    path = _trade_log_path(data_dir)
    file_exists = os.path.isfile(path)

    signals_fired = score_data.get("signals_fired", "")
    if isinstance(signals_fired, list):
        signals_fired = ",".join(signals_fired)

    row = {
        "date": date,
        "ticker": ticker,
        "action": action,
        "quantity": qty,
        "price": price,
        "position_type": position_type,
        "cost_price": cost_price,
        "score_at_entry": score_data.get("adjusted_score", ""),
        "signals_at_entry": signals_fired,
        "exit_date": "",
        "exit_price": "",
        "exit_quantity": "",
        "pnl_pct": "",
        "pnl_jpy": "",
    }

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def record_trade_exit(ticker, position_type, exit_date, exit_price, exit_qty, data_dir) -> None:
    """
    Find the last BUY entry for ticker+position_type with empty exit_date,
    calculate PnL, and rewrite the entire trade_log.csv with that row updated.
    """
    path = _trade_log_path(data_dir)
    if not os.path.isfile(path):
        return

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Find last matching open BUY entry
    target_idx = None
    for i, row in enumerate(rows):
        if (row.get("ticker") == ticker
                and row.get("position_type") == position_type
                and row.get("action") == "BUY"
                and not row.get("exit_date")):
            target_idx = i

    if target_idx is None:
        return

    # Update exit fields
    rows[target_idx]["exit_date"]     = exit_date
    rows[target_idx]["exit_price"]    = exit_price
    rows[target_idx]["exit_quantity"] = exit_qty

    # Calculate PnL with error handling
    try:
        cost = float(rows[target_idx]["cost_price"]) if rows[target_idx]["cost_price"] else float(rows[target_idx]["price"])
        if cost > 0:
            pnl_pct = (float(exit_price) - cost) / cost * 100
            pnl_jpy = (float(exit_price) - cost) * int(exit_qty)
        else:
            pnl_pct, pnl_jpy = "", ""
    except (ValueError, ZeroDivisionError):
        pnl_pct, pnl_jpy = "", ""

    rows[target_idx]["pnl_pct"]       = pnl_pct
    rows[target_idx]["pnl_jpy"]       = pnl_jpy

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
