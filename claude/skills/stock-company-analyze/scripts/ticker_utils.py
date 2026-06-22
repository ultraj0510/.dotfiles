"""Ticker normalization for Japanese stocks."""
import re

_TICKER_RE = re.compile(r"^(\d{4}|\d{3}[A-Za-z])(?:\.T)?$")


def normalize_ticker(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    m = _TICKER_RE.fullmatch(raw.strip().upper())
    if not m:
        return None
    return m.group(1).upper()
