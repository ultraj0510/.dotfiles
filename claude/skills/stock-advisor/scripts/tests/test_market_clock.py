from datetime import datetime
from zoneinfo import ZoneInfo

from market_clock import classify_market_session, is_price_stale

JST = ZoneInfo("Asia/Tokyo")


def test_classify_market_session_open_after_0900_weekday():
    now = datetime(2026, 6, 1, 9, 21, tzinfo=JST)
    assert classify_market_session(now) == "open"


def test_previous_business_day_price_is_stale_after_open():
    now = datetime(2026, 6, 1, 9, 21, tzinfo=JST)
    stale = is_price_stale(price_date="2026-05-29", now=now)
    assert stale["is_stale"] is True
    assert stale["reason"] == "previous_business_day_after_market_open"


def test_same_day_price_is_not_stale_after_open():
    now = datetime(2026, 6, 1, 9, 21, tzinfo=JST)
    stale = is_price_stale(price_date="2026-06-01", now=now)
    assert stale["is_stale"] is False
    assert stale["reason"] == ""
