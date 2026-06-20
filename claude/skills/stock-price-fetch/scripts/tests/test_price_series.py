import math

import pandas as pd
import pytest

from price_series import (
    PriceDataError,
    has_new_corporate_action,
    merge_bars,
    normalize_daily,
    normalize_intraday,
)


def test_normalize_daily_preserves_prices_actions_and_nulls():
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [110.0],
            "Low": [95.0],
            "Close": [105.0],
            "Adj Close": [103.0],
            "Volume": [1200],
            "Dividends": [math.nan],
            "Stock Splits": [0.0],
        },
        index=pd.to_datetime(["2026-06-20"]),
    )

    assert normalize_daily(frame) == [{
        "date": "2026-06-20",
        "open": 100.0,
        "high": 110.0,
        "low": 95.0,
        "close": 105.0,
        "adjusted_close": 103.0,
        "volume": 1200,
        "dividend": None,
        "stock_split": 0.0,
    }]


def test_normalize_intraday_converts_to_jst_iso_timestamp():
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Adj Close": [100.5],
            "Volume": [300],
        },
        index=pd.to_datetime(["2026-06-20 01:00:00+00:00"]),
    )

    result = normalize_intraday(frame)

    assert result[0]["timestamp"] == "2026-06-20T10:00:00+09:00"


def test_rejects_impossible_ohlc():
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [90.0],
            "Low": [95.0],
            "Close": [105.0],
            "Adj Close": [105.0],
            "Volume": [100],
            "Dividends": [0.0],
            "Stock Splits": [0.0],
        },
        index=pd.to_datetime(["2026-06-20"]),
    )

    with pytest.raises(PriceDataError, match="invalid_ohlc"):
        normalize_daily(frame)


def test_merge_replaces_overlap_and_sorts():
    existing = [
        {"date": "2026-06-19", "close": 99.0},
        {"date": "2026-06-20", "close": 100.0},
    ]
    incoming = [
        {"date": "2026-06-20", "close": 101.0},
        {"date": "2026-06-23", "close": 102.0},
    ]

    assert merge_bars(existing, incoming, "date") == [
        {"date": "2026-06-19", "close": 99.0},
        {"date": "2026-06-20", "close": 101.0},
        {"date": "2026-06-23", "close": 102.0},
    ]


def test_detects_new_dividend_or_split_only():
    existing = [{"date": "2026-06-20", "dividend": 0.0, "stock_split": 0.0}]
    assert has_new_corporate_action(
        existing,
        [{"date": "2026-06-20", "dividend": 10.0, "stock_split": 0.0}],
    )
    assert not has_new_corporate_action(
        existing,
        [{"date": "2026-06-20", "dividend": 0.0, "stock_split": 0.0}],
    )
