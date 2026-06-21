import re


PATTERN = re.compile(r"^(?:\d{4}|\d{3}[A-Z])$")


def normalize_ticker(value):
    if not isinstance(value, str):
        return None
    normalized = value.upper()
    return normalized if PATTERN.fullmatch(normalized) else None


def to_yahoo_symbol(ticker):
    if normalize_ticker(ticker) != ticker:
        raise ValueError("ticker must be normalized")
    return f"{ticker}.T"
