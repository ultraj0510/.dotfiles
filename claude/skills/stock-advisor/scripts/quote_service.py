from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

from data_utils import safe_float, yf_retry
from market_clock import classify_market_session

JST = ZoneInfo("Asia/Tokyo")


def _quote_time(info: dict) -> str | None:
    ts = info.get("regularMarketTime")
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=JST).isoformat()


def normalize_quote_from_info(ticker: str, info: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(JST)
    market_session = classify_market_session(now)
    for key in ("regularMarketPrice", "currentPrice"):
        price = safe_float(info.get(key))
        if price is not None:
            return {
                "ticker": ticker,
                "price": price,
                "source": key,
                "as_of": _quote_time(info) or now.astimezone(JST).isoformat(),
                "market_session": market_session,
                "is_stale": False,
                "staleness_reason": "",
            }
    previous = safe_float(info.get("regularMarketPreviousClose"))
    return {
        "ticker": ticker,
        "price": previous,
        "source": "regularMarketPreviousClose",
        "as_of": _quote_time(info),
        "market_session": market_session,
        "is_stale": market_session == "open",
        "staleness_reason": "previous_close_fallback" if market_session == "open" else "",
    }


def fetch_quote(ticker: str, now: datetime | None = None) -> dict:
    info = yf_retry(lambda: yf.Ticker(ticker).info)
    return normalize_quote_from_info(ticker, info, now=now)
