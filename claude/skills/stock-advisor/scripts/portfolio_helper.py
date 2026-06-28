from datetime import date


def check_credit_expiry(holding: dict) -> bool:
    """Return True if this credit position has an urgent expiry (within 30 days)."""
    if holding.get("position_type") != "信用":
        return False
    expiry = holding.get("expiry_date")
    if not expiry:
        return False
    try:
        expiry_date = date.fromisoformat(expiry)
        return (expiry_date - date.today()).days <= 30
    except (ValueError, TypeError):
        return False


def merge_portfolio_context(portfolio: dict, analysis: dict) -> dict:
    """Merge portfolio holdings and account data with analysis v2.0 output.

    Returns a daily_actions entry dict with:
    - ticker, name, holdings[], analysis{}, today_action, overridden, override_reason,
      order_candidates[], triggers[]
    """
    from copy import deepcopy

    port = deepcopy(portfolio)
    ana = deepcopy(analysis)

    ana_ticker = ana.get("ticker", "")
    # Normalize: strip ".T" suffix for matching
    normalized_ana = ana_ticker.replace(".T", "")

    matched_holdings = []
    total_assets = port.get("account", {}).get("total_assets", 1)
    has_credit_expiry_risk = False
    margin_reasons = []
    position_over_cap = False

    # Check account-level margin ratio first
    margin_ratio = port.get("account", {}).get("margin_ratio", 100)
    low_margin = margin_ratio < 30

    for h in port.get("holdings", []):
        h_ticker = h.get("ticker", "")
        h_normalized = h_ticker.replace(".T", "")
        if h_normalized != normalized_ana:
            continue

        cost_price = h.get("cost_price", 1)
        current_price = h.get("current_price", 0)
        quantity = h.get("quantity", 0)
        pnl_pct = ((current_price - cost_price) / cost_price) * 100 if cost_price else 0.0
        weight_pct = (current_price * quantity / total_assets) * 100 if total_assets else 0.0

        entry = dict(h)
        entry["pnl_pct"] = round(pnl_pct, 2)
        entry["weight_pct"] = round(weight_pct, 2)

        # Check credit expiry for this holding
        if h.get("position_type") == "信用" and check_credit_expiry(h):
            has_credit_expiry_risk = True

        if weight_pct > 20:
            position_over_cap = True

        matched_holdings.append(entry)

    # Determine override: credit expiry or low margin
    today_action = ana.get("execution_posture", "NO_TRADE")
    overridden = False
    override_reason = ""

    if has_credit_expiry_risk:
        margin_reasons.append("信用期限")
    if low_margin:
        margin_reasons.append(f"保証金率{margin_ratio}%")

    if margin_reasons:
        today_action = "REDUCE"
        overridden = True
        override_reason = "; ".join(margin_reasons)

    risk_flags = list(ana.get("risk_flags", []))
    if position_over_cap:
        risk_flags.append("position_over_cap_watch")

    # Inject computed risk_flags into analysis block for downstream consumers
    ana["risk_flags"] = risk_flags

    # Get name from the first matched holding if available
    name = matched_holdings[0].get("name", "") if matched_holdings else ""

    return {
        "ticker": ana_ticker,
        "name": name,
        "holdings": matched_holdings,
        "analysis": ana,
        "today_action": today_action,
        "overridden": overridden,
        "override_reason": override_reason,
        "order_candidates": [],
        "triggers": ana.get("monitoring_triggers", []),
        "risk_flags": risk_flags,
    }
