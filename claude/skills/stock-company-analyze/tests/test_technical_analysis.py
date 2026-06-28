from technical_analysis import normalize_direction, run_technical_analysis


def test_normalize_direction_buy():
    for raw in ("STRONG_BUY", "BUY", "HOLD_BUY"):
        assert normalize_direction(raw) == "BUY", f"{raw} -> BUY"


def test_normalize_direction_hold():
    assert normalize_direction("HOLD") == "HOLD"


def test_normalize_direction_sell():
    for raw in ("HOLD_SELL", "SELL", "STRONG_SELL"):
        assert normalize_direction(raw) == "SELL", f"{raw} -> SELL"


def test_normalize_direction_unknown():
    assert normalize_direction("UNKNOWN") == "HOLD"
    assert normalize_direction("") == "HOLD"
