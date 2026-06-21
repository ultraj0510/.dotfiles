import pytest

from ticker import normalize_ticker, to_yahoo_symbol


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3932", "3932"), ("285A", "285A"), ("285a", "285A")],
)
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", " 3932", "3932 ", "123", "12345", "28A", "bad;cmd"])
def test_rejects_invalid_ticker(raw):
    assert normalize_ticker(raw) is None


def test_yahoo_symbol():
    assert to_yahoo_symbol("285A") == "285A.T"
