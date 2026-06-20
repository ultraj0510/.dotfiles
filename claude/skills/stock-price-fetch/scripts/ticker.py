import re


_TICKER_PATTERN = re.compile(r"^(?:\d{4}|\d{3}[A-Z])$")


def normalize_ticker(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.upper()
    if not _TICKER_PATTERN.fullmatch(normalized):
        return None
    return normalized


def to_provider_symbol(ticker: str) -> str:
    if normalize_ticker(ticker) != ticker:
        raise ValueError("ticker must be normalized")
    return f"{ticker}.T"
