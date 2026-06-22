import pytest
from ticker_utils import normalize_ticker

@pytest.mark.parametrize("raw,expected", [
    ("285A", "285A"), ("285A.T", "285A"), ("285a", "285A"),
    ("3932", "3932"), ("3932.T", "3932"),
])
def test_valid(raw, expected):
    assert normalize_ticker(raw) == expected

@pytest.mark.parametrize("raw", ["", "ABC", "12", "12345", None])
def test_invalid(raw):
    assert normalize_ticker(raw) is None
