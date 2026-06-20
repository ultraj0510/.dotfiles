"""Tests for ticker validation and normalization."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import ticker_is_valid

VALID_TICKERS = [
    "3932",
    "7203",
    "285A",
    "130A",
    "9999",
    "1000",
]

INVALID_TICKERS = [
    "123",       # only 3 digits, no letter
    "1234A",     # 5 chars
    "28A",       # only 2 digits
    "ABCDE",     # no digits
    "ABC",       # no digits
    "12345",     # 5 digits
    "12A",       # 3 chars
    "",          # empty
    "   ",       # whitespace
    "3932 ",     # trailing space
    "bad?token=secret",  # injection
    "\n3932",    # control char
]


@pytest.mark.parametrize("ticker", VALID_TICKERS)
def test_valid_tickers(ticker):
    assert ticker_is_valid(ticker), f"{ticker} should be valid"


@pytest.mark.parametrize("ticker", INVALID_TICKERS)
def test_invalid_tickers(ticker):
    assert not ticker_is_valid(ticker), f"{ticker} should be invalid"
