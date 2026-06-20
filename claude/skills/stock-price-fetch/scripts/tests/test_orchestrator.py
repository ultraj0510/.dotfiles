from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from fetch_stock_price import fetch_stock_price


JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 6, 21, 12, 0, tzinfo=JST)


def daily_frame(dates, dividend=0.0, split=0.0):
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "Open": [100.0] * len(index),
            "High": [110.0] * len(index),
            "Low": [90.0] * len(index),
            "Close": [105.0] * len(index),
            "Adj Close": [103.0] * len(index),
            "Volume": [1000] * len(index),
            "Dividends": [dividend] * len(index),
            "Stock Splits": [split] * len(index),
        },
        index=index,
    )


def intraday_frame(timestamps):
    index = pd.to_datetime(timestamps)
    return pd.DataFrame(
        {
            "Open": [100.0] * len(index),
            "High": [110.0] * len(index),
            "Low": [90.0] * len(index),
            "Close": [105.0] * len(index),
            "Adj Close": [105.0] * len(index),
            "Volume": [1000] * len(index),
        },
        index=index,
    )


class FakeProvider:
    def __init__(self, daily_results, intraday_results):
        self.daily_results = list(daily_results)
        self.intraday_results = list(intraday_results)
        self.daily_calls = []
        self.intraday_calls = []

    def fetch_daily(self, symbol, start, end):
        self.daily_calls.append((symbol, start, end))
        return self.daily_results.pop(0)

    def fetch_intraday(self, symbol, start, end):
        self.intraday_calls.append((symbol, start, end))
        return self.intraday_results.pop(0)


def test_initial_sync_requests_five_years_and_sixty_days(tmp_path):
    provider = FakeProvider(
        [daily_frame(["2026-06-20"])],
        [intraday_frame(["2026-06-20 10:00+09:00"])],
    )

    result = fetch_stock_price(
        "285a",
        tmp_path,
        now=NOW,
        provider=provider,
        minimum_daily_rows=1,
    )

    assert result["ticker"] == "285A"
    assert result["sync"]["mode"] == "initial"
    assert provider.daily_calls[0][1].date().isoformat() == "2021-06-21"
    assert provider.intraday_calls[0][1].date().isoformat() == "2026-04-22"
    assert result["summary"]["usable"] is True
    assert result["data"]["daily"]["status"] == "ok"
    assert result["data"]["intraday_1h"]["status"] == "ok"
    assert result["data"]["daily"]["fetched_at"]
    assert result["data"]["intraday_1h"]["fetched_at"]


def test_incremental_sync_uses_overlap_and_replaces_existing_bars(tmp_path):
    first = FakeProvider(
        [daily_frame(["2026-06-10", "2026-06-20"])],
        [intraday_frame(["2026-06-20 10:00+09:00"])],
    )
    fetch_stock_price(
        "285A",
        tmp_path,
        now=NOW,
        provider=first,
        minimum_daily_rows=1,
    )
    second = FakeProvider(
        [daily_frame(["2026-06-20", "2026-06-23"])],
        [intraday_frame(["2026-06-20 10:00+09:00", "2026-06-20 11:00+09:00"])],
    )

    result = fetch_stock_price(
        "285A",
        tmp_path,
        now=datetime(2026, 6, 23, 18, 0, tzinfo=JST),
        provider=second,
        minimum_daily_rows=1,
    )

    assert result["sync"]["mode"] == "incremental"
    assert second.daily_calls[0][1].date().isoformat() == "2026-06-10"
    assert second.intraday_calls[0][1].isoformat() == "2026-06-20T08:00:00+09:00"
    assert [bar["date"] for bar in result["data"]["daily"]["bars"]] == [
        "2026-06-10",
        "2026-06-20",
        "2026-06-23",
    ]
    assert len(result["data"]["intraday_1h"]["bars"]) == 2


def test_new_corporate_action_triggers_full_daily_reconciliation(tmp_path):
    first = FakeProvider(
        [daily_frame(["2026-06-20"])],
        [intraday_frame(["2026-06-20 10:00+09:00"])],
    )
    fetch_stock_price(
        "3932",
        tmp_path,
        now=NOW,
        provider=first,
        minimum_daily_rows=1,
    )
    provider = FakeProvider(
        [
            daily_frame(["2026-06-20"], dividend=10.0),
            daily_frame(["2021-06-21", "2026-06-20"], dividend=10.0),
        ],
        [intraday_frame(["2026-06-20 10:00+09:00"])],
    )

    result = fetch_stock_price(
        "3932",
        tmp_path,
        now=datetime(2026, 6, 23, 18, 0, tzinfo=JST),
        provider=provider,
        minimum_daily_rows=1,
    )

    assert result["sync"]["mode"] == "full_reconcile"
    assert result["sync"]["reconcile_reason"] == "corporate_action"
    assert len(provider.daily_calls) == 2
    assert provider.daily_calls[1][1].date().isoformat() == "2021-06-23"


def test_invalid_ticker_returns_failed_without_provider_call(tmp_path):
    provider = FakeProvider([], [])

    result = fetch_stock_price("bad;command", tmp_path, now=NOW, provider=provider)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "ticker_invalid"
    assert provider.daily_calls == []


def test_intraday_failure_preserves_daily_and_returns_partial(tmp_path):
    """P1#1: intraday failure must not wipe existing daily data."""
    # First: establish both series
    first = FakeProvider(
        [daily_frame(["2026-06-10", "2026-06-20"])],
        [intraday_frame(["2026-06-20 10:00+09:00"])],
    )
    fetch_stock_price("3932", tmp_path, now=NOW, provider=first, minimum_daily_rows=1)

    # Second: intraday fails, daily succeeds
    class IntradayFailureProvider(FakeProvider):
        def fetch_intraday(self, symbol, start, end):
            from yahoo_provider import PriceProviderError
            raise PriceProviderError("provider_failed", True, "safe failure")

    provider = IntradayFailureProvider(
        [daily_frame(["2026-06-20", "2026-06-23"])],
        [],
    )

    result = fetch_stock_price(
        "3932",
        tmp_path,
        now=datetime(2026, 6, 23, 18, 0, tzinfo=JST),
        provider=provider,
        minimum_daily_rows=1,
    )

    assert result["status"] == "partial"
    assert len(result["data"]["daily"]["bars"]) == 3  # 06-10, 06-20, 06-23 merged
    assert result["data"]["daily"]["status"] == "ok"
    assert result["data"]["daily"]["fetched_at"]  # newly fetched
    # Intraday preserved from previous run
    assert len(result["data"]["intraday_1h"]["bars"]) == 1
    assert result["data"]["intraday_1h"]["status"] == "ok"
    assert result["summary"]["usable"] is True


def test_daily_failure_preserves_intraday_with_refresh(tmp_path):
    """P1#1: refresh with daily failure must preserve old daily via safety net."""
    # First: establish both series
    first = FakeProvider(
        [daily_frame(["2026-06-10", "2026-06-20"])],
        [intraday_frame(["2026-06-20 10:00+09:00"])],
    )
    fetch_stock_price("3932", tmp_path, now=NOW, provider=first, minimum_daily_rows=1)

    # Second: refresh + daily fails, intraday succeeds
    class DailyFailingProvider(FakeProvider):
        def fetch_daily(self, symbol, start, end):
            from yahoo_provider import PriceProviderError
            raise PriceProviderError("provider_failed", True, "safe failure")

    provider = DailyFailingProvider(
        [],
        [intraday_frame(["2026-06-20 10:00+09:00", "2026-06-20 11:00+09:00"])],
    )

    result = fetch_stock_price(
        "3932",
        tmp_path,
        now=datetime(2026, 6, 23, 18, 0, tzinfo=JST),
        provider=provider,
        refresh=True,
        minimum_daily_rows=1,
    )

    assert result["status"] == "partial"
    # Daily preserved from previous (safety net)
    assert len(result["data"]["daily"]["bars"]) == 2
    assert result["data"]["daily"]["status"] == "ok"
    # Intraday is new
    assert len(result["data"]["intraday_1h"]["bars"]) == 2
    assert result["data"]["intraday_1h"]["status"] == "ok"
    assert result["summary"]["usable"] is True


def test_same_incremental_payload_is_idempotent(tmp_path):
    first = FakeProvider(
        [daily_frame(["2026-06-20"])],
        [intraday_frame(["2026-06-20 10:00+09:00"])],
    )
    fetch_stock_price("3932", tmp_path, now=NOW, provider=first, minimum_daily_rows=1)
    repeat = FakeProvider(
        [daily_frame(["2026-06-20"])],
        [intraday_frame(["2026-06-20 10:00+09:00"])],
    )

    result = fetch_stock_price("3932", tmp_path, now=NOW, provider=repeat, minimum_daily_rows=1)

    assert len(result["data"]["daily"]["bars"]) == 1
    assert len(result["data"]["intraday_1h"]["bars"]) == 1
