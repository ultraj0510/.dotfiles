from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from yahoo_provider import PriceProviderError, YahooPriceProvider


JST = ZoneInfo("Asia/Tokyo")


class FakeTicker:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame.copy()


def test_fetch_daily_uses_unadjusted_prices_and_actions():
    frame = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2026-06-20"]))
    fake = FakeTicker(frame)
    provider = YahooPriceProvider(ticker_factory=lambda symbol: fake)

    result = provider.fetch_daily(
        "285A.T",
        datetime(2021, 6, 21, tzinfo=JST),
        datetime(2026, 6, 22, tzinfo=JST),
    )

    assert len(result) == 1
    assert fake.calls == [{
        "start": datetime(2021, 6, 21, tzinfo=JST),
        "end": datetime(2026, 6, 22, tzinfo=JST),
        "interval": "1d",
        "auto_adjust": False,
        "actions": True,
        "repair": True,
        "prepost": False,
        "raise_errors": True,
    }]


def test_fetch_intraday_uses_one_hour_regular_session():
    frame = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2026-06-20 10:00+09:00"]))
    fake = FakeTicker(frame)
    provider = YahooPriceProvider(ticker_factory=lambda symbol: fake)
    start = datetime(2026, 4, 22, tzinfo=JST)
    end = datetime(2026, 6, 22, tzinfo=JST)

    provider.fetch_intraday("285A.T", start, end)

    assert fake.calls[0]["interval"] == "1h"
    assert fake.calls[0]["prepost"] is False


def test_provider_wraps_upstream_failure_without_response_content():
    class BrokenTicker:
        def history(self, **kwargs):
            raise RuntimeError("secret upstream body")

    provider = YahooPriceProvider(ticker_factory=lambda symbol: BrokenTicker())

    with pytest.raises(PriceProviderError) as error:
        provider.fetch_daily(
            "3932.T",
            datetime(2021, 6, 21, tzinfo=JST),
            datetime(2026, 6, 22, tzinfo=JST),
        )

    assert error.value.code == "provider_failed"
    assert error.value.retryable is True
    assert "secret upstream body" not in str(error.value)
