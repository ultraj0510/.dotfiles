import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fetch_stock_price import fetch_stock_price

JST = ZoneInfo("Asia/Tokyo")


class FakeBenchmarkProvider:
    """Returns TOPIX-like daily bars without network access."""
    def fetch_daily(self, symbol, start, end):
        import pandas as pd
        dates = pd.date_range(start=start, end=end, freq="B", tz=JST)
        n = len(dates)
        return pd.DataFrame({
            "Open": [2800.0 + i for i in range(n)],
            "High": [2810.0 + i for i in range(n)],
            "Low": [2790.0 + i for i in range(n)],
            "Close": [2805.0 + i for i in range(n)],
            "Adj Close": [2805.0 + i for i in range(n)],
            "Volume": [0] * n,
            "Dividends": [0.0] * n,
            "Stock Splits": [0.0] * n,
        }, index=dates)

    def fetch_intraday(self, symbol, start, end):
        from yahoo_provider import PriceProviderError
        raise PriceProviderError("no_data", False, "No intraday for benchmark")


def test_benchmark_output_schema(tmp_path):
    result = fetch_stock_price(
        "TOPIX",
        data_dir=tmp_path,
        now=datetime(2026, 6, 22, 15, 0, tzinfo=JST),
        benchmark="TOPIX",
        provider=FakeBenchmarkProvider(),
    )
    assert result["schema_version"] == "1.1"
    assert result["instrument_type"] == "benchmark"
    assert result["benchmark_id"] == "TOPIX"
    assert result["ticker"] == "TOPIX"
    assert result["provider_symbol"] == "^TOPX"
    assert result["status"] in ("success", "partial")


def test_benchmark_daily_has_bars(tmp_path):
    result = fetch_stock_price(
        "TOPIX",
        data_dir=tmp_path,
        now=datetime(2026, 6, 22, 15, 0, tzinfo=JST),
        benchmark="TOPIX",
        provider=FakeBenchmarkProvider(),
    )
    daily = result["data"]["daily"]
    assert daily["status"] == "ok"
    assert len(daily["bars"]) > 0
    bar = daily["bars"][0]
    required_keys = {"date", "open", "high", "low", "close", "volume"}
    assert required_keys.issubset(bar.keys()), f"Missing keys: {required_keys - set(bar.keys())}"


def test_benchmark_intraday_not_available(tmp_path):
    result = fetch_stock_price(
        "TOPIX",
        data_dir=tmp_path,
        now=datetime(2026, 6, 22, 15, 0, tzinfo=JST),
        benchmark="TOPIX",
        provider=FakeBenchmarkProvider(),
    )
    intraday = result["data"]["intraday_1h"]
    assert intraday["status"] == "not_available"
    assert len(intraday["bars"]) == 0


def test_benchmark_uses_correct_yahoo_symbol(tmp_path):
    result = fetch_stock_price(
        "TOPIX",
        data_dir=tmp_path,
        now=datetime(2026, 6, 22, 15, 0, tzinfo=JST),
        benchmark="TOPIX",
        provider=FakeBenchmarkProvider(),
    )
    assert result["provider_symbol"] == "^TOPX"


def test_normal_stock_unchanged(tmp_path):
    """Verify stock fetch still works without benchmark."""
    result = fetch_stock_price(
        "285A",
        data_dir=tmp_path,
        now=datetime(2026, 6, 22, 15, 0, tzinfo=JST),
        provider=FakeBenchmarkProvider(),
    )
    assert result["ticker"] == "285A"
    assert result["provider_symbol"] == "285A.T"
    assert result.get("instrument_type") != "benchmark"
    assert result.get("benchmark_id") is None


def test_benchmark_saved_to_correct_path(tmp_path):
    from price_store import PriceStore
    store = PriceStore(tmp_path)
    path = store.path_for("TOPIX")
    assert str(path).endswith("TOPIX/raw/stock-price-fetch/prices.json")
