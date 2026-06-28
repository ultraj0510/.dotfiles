"""Deterministic bounded OHLC forecast for analysis.json."""
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def build_price_forecast(
    *,
    ticker: str,
    as_of,
    technical: dict,
    fundamental: dict,
    integrated: dict,
    market_metrics: dict,
    llm_result: dict,
) -> dict:
    """Return an additive forecast block for analysis.json."""
    indicators = technical.get("indicators", {})
    close = indicators.get("close")
    atr = indicators.get("atr")

    if close is None:
        return _unavailable("missing_close")
    if atr is None:
        return _unavailable("missing_atr")

    # Parse as_of to determine target session
    target = _determine_target(as_of)

    trend_state = technical.get("trend_state", "unknown")
    tech_direction = technical.get("direction", "HOLD")
    bb_pos = indicators.get("bollinger", {}).get("position_pct")
    topix = market_metrics.get("topix_relative")

    # Compute ATR multiples from technical state
    bias = _compute_bias(trend_state, tech_direction, bb_pos, topix,
                         integrated.get("risk_flags", []),
                         fundamental.get("catalysts", []))

    # Generate OHLC within ATR guardrails
    ohlc = _generate_ohlc(close, atr, bias)

    # Validate
    ok, reason = validate_forecast_guardrails(ohlc, close, atr)
    confidence = "medium" if ok else "low"

    # Build reasoning
    reasoning = _build_reasoning(bias, bb_pos, topix, fundamental.get("catalysts", []))

    return {
        "target": target,
        "target_date": _target_date(as_of),
        "base_price": close,
        "ohlc": ohlc,
        "confidence": confidence,
        "unavailable_reason": None,
        "inputs": {
            "close": close,
            "atr": atr,
            "trend_state": trend_state,
            "technical_direction": tech_direction,
            "bollinger_position_pct": bb_pos,
            "topix_relative": topix,
            "near_term_catalysts": [c for c in fundamental.get("catalysts", [])[:2]],
            "risk_flags": integrated.get("risk_flags", []),
        },
        "bias": bias,
        "reasoning": reasoning,
    }


def _determine_target(as_of) -> str:
    """Determine whether forecast targets same_day or next_session."""
    if isinstance(as_of, str):
        try:
            as_of = datetime.fromisoformat(as_of)
        except ValueError:
            return "next_session"
    # Weekday check: Mon-Fri, before 15:00 JST = same_day
    if hasattr(as_of, 'weekday'):
        if as_of.weekday() < 5 and as_of.hour < 15:
            return "same_day"
    return "next_session"


def _target_date(as_of) -> str | None:
    """Return target date string in YYYY-MM-DD."""
    if isinstance(as_of, str):
        try:
            as_of = datetime.fromisoformat(as_of)
        except ValueError:
            return None
    if hasattr(as_of, 'date'):
        return as_of.date().isoformat()
    return None


def _compute_bias(trend_state, tech_direction, bb_pos, topix,
                  risk_flags, catalysts) -> dict:
    """Compute directional bias from technical state."""
    trend_coef = {
        "strong_uptrend": 1.2, "weak_uptrend": 1.1,
        "ranging": 1.0,
        "weak_downtrend": 0.9, "strong_downtrend": 0.8,
        "unknown": 1.0,
    }
    up_mult = trend_coef.get(trend_state, 1.0)

    # Directional tilt
    if tech_direction == "BUY":
        up_mult += 0.1
    elif tech_direction == "SELL":
        up_mult -= 0.1

    # BB position adjustment: near upper -> reduce upside, near lower -> reduce downside
    if bb_pos is not None and bb_pos > 80:
        up_mult -= 0.1
    elif bb_pos is not None and bb_pos < 20:
        up_mult += 0.1  # easier to bounce

    # Clamp to [0.5, 1.8]
    up_mult = max(0.5, min(1.8, up_mult))
    down_mult = 2.0 - up_mult

    direction = "up" if up_mult > 1.05 else ("down" if up_mult < 0.95 else "neutral")
    if up_mult > 1.15:
        strength = "strong"
    elif abs(up_mult - 1.0) > 0.05:
        strength = "moderate"
    else:
        strength = "weak"

    return {
        "direction": direction,
        "strength": strength,
        "upside_atr_multiple": round(up_mult, 2),
        "downside_atr_multiple": round(down_mult, 2),
    }


def _generate_ohlc(close, atr, bias) -> dict:
    """Generate bounded OHLC forecast."""
    up_mult = bias["upside_atr_multiple"]
    down_mult = bias["downside_atr_multiple"]

    high = close + atr * up_mult
    low = close - atr * down_mult

    # Open: slight directional tilt
    if bias["direction"] == "up":
        open_price = close * 1.003
    elif bias["direction"] == "down":
        open_price = close * 0.997
    else:
        open_price = close

    # Close: tilt based on direction + strength
    tilt = 0.002 if bias["strength"] == "weak" else (0.005 if bias["strength"] == "moderate" else 0.008)
    if bias["direction"] == "up":
        close_price = close * (1 + tilt)
    elif bias["direction"] == "down":
        close_price = close * (1 - tilt)
    else:
        close_price = close

    return {
        "open": round(open_price),
        "high": round(high),
        "low": round(low),
        "close": round(close_price),
    }


def _build_reasoning(bias, bb_pos, topix, catalysts) -> str:
    """Build Japanese reasoning string."""
    parts = []
    if bias["direction"] == "up":
        parts.append("テクニカルは上方向バイアス")
    elif bias["direction"] == "down":
        parts.append("テクニカルは下方向バイアス")
    else:
        parts.append("テクニカルは方向感に乏しい")

    if bb_pos is not None and bb_pos > 80:
        parts.append("BB位置が高く上値は限定的")
    elif bb_pos is not None and bb_pos < 20:
        parts.append("BB位置が低く下値は限定的")

    if topix:
        parts.append(f"TOPIX対比: {topix}")

    if catalysts:
        parts.append(f"近いカタリスト: {', '.join(catalysts[:2])}")

    return "。".join(parts) + "。"


def validate_forecast_guardrails(ohlc, base_price, atr) -> tuple[bool, str]:
    """Validate OHLC against guardrails. Returns (ok, reason)."""
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]

    if h < max(o, c, base_price):
        return False, f"high={h} below max(open={o}, close={c}, base={base_price})"
    if l > min(o, c, base_price):
        return False, f"low={l} above min(open={o}, close={c}, base={base_price})"
    if l <= 0:
        return False, "low <= 0"
    if h - l > 4 * atr:
        return False, f"range={h-l} > 4*atr={4*atr}"
    if o < l or o > h:
        return False, f"open={o} outside [{l}, {h}]"
    if c < l or c > h:
        return False, f"close={c} outside [{l}, {h}]"

    return True, ""


def _unavailable(reason: str) -> dict:
    return {
        "target": "next_session",
        "target_date": None,
        "base_price": None,
        "ohlc": None,
        "confidence": "unavailable",
        "unavailable_reason": reason,
        "inputs": {},
        "bias": None,
        "reasoning": f"必須データ({reason})が欠損しているため4本値目安を生成しない。",
    }
