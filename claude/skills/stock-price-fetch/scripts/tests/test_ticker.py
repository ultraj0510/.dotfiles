import pytest

from ticker import normalize_ticker, to_provider_symbol


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("3932", "3932"),
        ("285A", "285A"),
        ("285a", "285A"),
    ],
)
def test_normalize_ticker_accepts_supported_codes(value, expected):
    assert normalize_ticker(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", " 3932", "3932 ", "123", "12345", "28A", "12AB", "bad;rm -rf"],
)
def test_normalize_ticker_rejects_invalid_input(value):
    assert normalize_ticker(value) is None


def test_to_provider_symbol_uses_tse_suffix():
    assert to_provider_symbol("285A") == "285A.T"
