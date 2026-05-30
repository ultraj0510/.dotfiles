"""Portfolio optimizer: position sizing, risk limits, margin urgency."""

import math

MAX_POSITION_PCT = 0.20
MAX_TRADE_RISK_PCT = 0.02
LOT_SIZE = 100
MARGIN_URGENT_DAYS = 30
MARGIN_WATCH_DAYS = 60


def floor_to_lot(shares: float) -> int:
    """Round down to the nearest lot size (100 shares)."""
    return int(math.floor(shares / LOT_SIZE) * LOT_SIZE)


def compute_buy_order_shares(
    total_assets: float,
    available_cash: float,
    current_position_value: float,
    entry_price: float,
    stop_loss: float,
    atr: float,
    correlation_concentration: bool = False,
) -> tuple[int, list[str]]:
    """Compute BUY order shares respecting risk budget, position cap, and cash.

    Returns (order_shares, vetoes).
    """
    vetoes = []

    if entry_price <= 0 or total_assets <= 0:
        return 0, ["invalid_params"]

    risk_budget = total_assets * MAX_TRADE_RISK_PCT
    per_share_risk = max(entry_price - stop_loss, atr * 2, entry_price * 0.03)
    if per_share_risk <= 0:
        per_share_risk = entry_price * 0.03

    risk_based = floor_to_lot(risk_budget / per_share_risk)

    max_position_value = total_assets * MAX_POSITION_PCT
    remaining_capacity = max_position_value - current_position_value
    cap_based = floor_to_lot(remaining_capacity / entry_price)

    cash_based = floor_to_lot(available_cash / entry_price)

    shares = min(risk_based, cap_based, cash_based)

    if correlation_concentration:
        shares = floor_to_lot(shares / 2)
        vetoes.append("correlation_concentration")

    if shares <= 0:
        vetoes.append("insufficient_capacity")

    return max(0, shares), vetoes


def compute_sell_order_shares(
    current_shares: int,
    recommended_reduce_shares: int,
) -> int:
    """SELL/REDUCE may never exceed current holdings."""
    return min(current_shares, max(0, recommended_reduce_shares))


def margin_expiry_vetoes(expiry_date_str: str | None, open_date_str: str | None = None) -> list[str]:
    """Return vetoes based on margin trade expiry urgency."""
    if not expiry_date_str:
        return []
    from datetime import date as dt_date
    try:
        expiry = dt_date.fromisoformat(expiry_date_str)
    except (ValueError, TypeError):
        return []
    days_left = (expiry - dt_date.today()).days
    vetoes = []
    if days_left < MARGIN_URGENT_DAYS:
        vetoes.append("margin_expiry_urgent")
    elif days_left < MARGIN_WATCH_DAYS:
        vetoes.append("margin_expiry_watch")
    return vetoes


def position_cap_vetoes(
    total_assets: float,
    current_position_value: float,
) -> list[str]:
    """Vetoes related to position concentration."""
    vetoes = []
    if total_assets > 0 and current_position_value / total_assets > MAX_POSITION_PCT:
        vetoes.append("position_over_cap")
    return vetoes
