"""Prove benchmark payload is compatible with existing PriceStore validator."""
from datetime import datetime
from zoneinfo import ZoneInfo
from price_store import PriceStore

JST = ZoneInfo("Asia/Tokyo")


def _benchmark_payload():
    """Exact shape that --benchmark TOPIX will produce."""
    now = datetime(2026, 6, 22, 15, 0, tzinfo=JST)
    return {
        "schema_version": "1.1",
        "run_id": "20260622T150000+0900-TOPIX",
        "ticker": "TOPIX",
        "provider_symbol": "^TOPX",
        "as_of": now.isoformat(),
        "status": "success",
        "instrument_type": "benchmark",
        "benchmark_id": "TOPIX",
        "sync": {
            "mode": "initial",
            "daily_requested_from": "2021-06-22",
            "intraday_requested_from": "2026-04-23T15:00:00+09:00",
            "reconcile_reason": None,
        },
        "data": {
            "exchange_timezone": "Asia/Tokyo",
            "currency": "JPY",
            "daily": {
                "status": "ok",
                "fetched_at": now.isoformat(),
                "data_as_of": "2026-06-22",
                "bars": [
                    {"date": "2026-06-19", "open": 2800.0, "high": 2815.0, "low": 2795.0, "close": 2810.0, "volume": 0},
                    {"date": "2026-06-22", "open": 2810.0, "high": 2825.0, "low": 2805.0, "close": 2820.0, "volume": 0},
                ],
            },
            "intraday_1h": {
                "status": "not_available",
                "fetched_at": now.isoformat(),
                "data_as_of": None,
                "bars": [],
            },
        },
        "sources": {
            "daily": {"provider": "yahoo_finance", "symbol": "^TOPX", "fetched_at": now.isoformat()},
            "intraday_1h": {"provider": "yahoo_finance", "symbol": "^TOPX", "fetched_at": now.isoformat()},
        },
        "errors": [],
        "summary": {
            "daily_rows": 2,
            "intraday_rows": 0,
            "daily_first_date": "2026-06-19",
            "daily_last_date": "2026-06-22",
            "intraday_first_timestamp": None,
            "intraday_last_timestamp": None,
            "usable": True,
        },
    }


def test_benchmark_round_trips_through_store(tmp_path):
    store = PriceStore(tmp_path)
    payload = _benchmark_payload()
    store.save("TOPIX", payload)
    loaded = store.load("TOPIX")
    assert loaded is not None, "PriceStore.load() rejected benchmark payload"
    assert loaded["ticker"] == "TOPIX"
    assert loaded["instrument_type"] == "benchmark"
    assert loaded["benchmark_id"] == "TOPIX"
    assert len(loaded["data"]["daily"]["bars"]) == 2


def test_benchmark_volume_zero_accepted(tmp_path):
    store = PriceStore(tmp_path)
    payload = _benchmark_payload()
    payload["data"]["daily"]["bars"][0]["volume"] = 0.0
    store.save("TOPIX", payload)
    loaded = store.load("TOPIX")
    assert loaded is not None, "Volume=0.0 should pass (vol >= 0 check)"


def test_benchmark_payload_passes_all_bar_checks(tmp_path):
    store = PriceStore(tmp_path)
    payload = _benchmark_payload()
    store.save("TOPIX", payload)
    loaded = store.load("TOPIX")
    assert loaded is not None
    daily = loaded["data"]["daily"]
    assert daily["status"] == "ok"
    assert daily["data_as_of"] == "2026-06-22"


def test_stock_payload_with_new_null_fields(tmp_path):
    store = PriceStore(tmp_path)
    payload = _benchmark_payload()
    payload["ticker"] = "285A"
    payload["provider_symbol"] = "285A.T"
    payload["instrument_type"] = None
    payload["benchmark_id"] = None
    payload["data"]["daily"]["bars"] = [
        {"date": "2026-06-19", "open": 108000.0, "high": 110000.0, "low": 107000.0, "close": 109200.0, "volume": 500000},
    ]
    payload["data"]["daily"]["data_as_of"] = "2026-06-19"
    payload["sync"]["daily_requested_from"] = "2021-06-19"
    store.save("285A", payload)
    loaded = store.load("285A")
    assert loaded is not None
