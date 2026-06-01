from datetime import datetime
from zoneinfo import ZoneInfo

from quote_service import normalize_quote_from_info

JST = ZoneInfo("Asia/Tokyo")


def test_normalize_quote_prefers_regular_market_price():
    now = datetime(2026, 6, 1, 9, 21, tzinfo=JST)
    info = {
        "regularMarketPrice": 7213,
        "regularMarketTime": 1780273260,
        "regularMarketPreviousClose": 7148,
    }
    quote = normalize_quote_from_info("7974.T", info, now=now)
    assert quote["price"] == 7213
    assert quote["source"] == "regularMarketPrice"
    assert quote["is_stale"] is False


def test_previous_close_fallback_is_marked_stale_after_open():
    now = datetime(2026, 6, 1, 9, 21, tzinfo=JST)
    info = {"regularMarketPreviousClose": 2397}
    quote = normalize_quote_from_info("1515.T", info, now=now)
    assert quote["price"] == 2397
    assert quote["source"] == "regularMarketPreviousClose"
    assert quote["is_stale"] is True
    assert quote["staleness_reason"] == "previous_close_fallback"
