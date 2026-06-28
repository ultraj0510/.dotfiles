"""Conflict matrix: fundamental rating vs technical direction."""

_CONFLICT_MATRIX = {
    ("BUY", "BUY"): {
        "investment_rating": "BUY",
        "execution_posture": "ACT_NOW",
        "reasoning": "ファンダメンタル・テクニカルともに強気。買い/買い増し候補。",
    },
    ("BUY", "HOLD"): {
        "investment_rating": "BUY",
        "execution_posture": "WAIT",
        "reasoning": "ファンダメンタルは強気だがテクニカルは中立。押し目待ち。",
    },
    ("BUY", "SELL"): {
        "investment_rating": "BUY",
        "execution_posture": "WAIT",
        "reasoning": "ファンダメンタルは強気だがテクニカルは弱気。調整後に買い検討。",
    },
    ("HOLD", "BUY"): {
        "investment_rating": "HOLD",
        "execution_posture": "NO_TRADE",
        "reasoning": "テクニカルは強気だがファンダメンタル中立。買い増し抑制。",
    },
    ("HOLD", "HOLD"): {
        "investment_rating": "HOLD",
        "execution_posture": "NO_TRADE",
        "reasoning": "ファンダメンタル・テクニカルともに中立。保有継続。",
    },
    ("HOLD", "SELL"): {
        "investment_rating": "HOLD",
        "execution_posture": "NO_TRADE",
        "reasoning": "テクニカル弱気だがファンダメンタル中立。ポジション見直し候補。",
    },
    ("SELL", "BUY"): {
        "investment_rating": "SELL",
        "execution_posture": "WAIT",
        "reasoning": "テクニカルは強気だがファンダメンタル弱気。反発売り検討。",
    },
    ("SELL", "HOLD"): {
        "investment_rating": "SELL",
        "execution_posture": "WAIT",
        "reasoning": "ファンダメンタル弱気。保有削減を検討。",
    },
    ("SELL", "SELL"): {
        "investment_rating": "SELL",
        "execution_posture": "ACT_NOW",
        "reasoning": "ファンダメンタル・テクニカルともに弱気。売却を強く検討。",
    },
}

_VALID_RATINGS = {"BUY", "HOLD", "SELL"}


def compute_integrated_judgment(fundamental_rating: str, technical_direction: str) -> dict:
    """Return investment_rating, execution_posture, and reasoning from conflict matrix.

    Invalid inputs default to "HOLD" / "HOLD".
    """
    fund = fundamental_rating if fundamental_rating in _VALID_RATINGS else "HOLD"
    tech = technical_direction if technical_direction in _VALID_RATINGS else "HOLD"
    return dict(_CONFLICT_MATRIX[(fund, tech)])
