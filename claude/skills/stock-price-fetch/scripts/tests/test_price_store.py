import json
import math

import pytest

from price_store import PriceStore


DAILY_BAR = {"date": "2026-06-20", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000}
INTRADAY_BAR = {"timestamp": "2026-06-20T10:00:00+09:00", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000}


def _daily_series(bars=None):
    bar_list = bars or []
    return {
        "status": "ok",
        "fetched_at": "2026-06-21T12:00:00+09:00",
        "data_as_of": bar_list[-1]["date"] if bar_list else None,
        "bars": bar_list,
    }

def _intraday_series(bars=None):
    bar_list = bars or []
    return {
        "status": "ok",
        "fetched_at": "2026-06-21T12:00:00+09:00",
        "data_as_of": bar_list[-1]["timestamp"] if bar_list else None,
        "bars": bar_list,
    }


def payload(ticker="285A"):
    return {
        "schema_version": "1.1",
        "ticker": ticker,
        "data": {"daily": _daily_series(), "intraday_1h": _intraday_series()},
    }


def test_save_uses_ticker_scoped_path_and_permissions(tmp_path):
    store = PriceStore(tmp_path)

    path = store.save("285A", payload())

    assert path == tmp_path / "285A" / "raw" / "stock-price-fetch" / "prices.json"
    assert json.loads(path.read_text())["ticker"] == "285A"
    assert path.stat().st_mode & 0o777 == 0o600


def test_load_rejects_wrong_ticker(tmp_path):
    store = PriceStore(tmp_path)
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload("3932")))

    assert store.load("285A") is None


def test_load_rejects_unknown_schema(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["schema_version"] = "2.0"
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_rejects_old_schema_1_0(tmp_path):
    store = PriceStore(tmp_path)
    old = {"schema_version": "1.0", "ticker": "285A", "data": {"daily": [], "intraday_1h": []}}
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(old))

    assert store.load("285A") is None


def test_save_replaces_existing_file_without_tmp_residue(tmp_path):
    store = PriceStore(tmp_path)
    store.save("285A", payload())
    updated = payload()
    updated["data"]["daily"] = _daily_series([DAILY_BAR])

    store.save("285A", updated)

    loaded = store.load("285A")
    assert loaded["data"]["daily"]["bars"] == [DAILY_BAR]
    assert list(tmp_path.rglob("*.tmp")) == []


def test_load_rejects_corrupt_bar_missing_keys(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{"date": "2026-06-20", "open": 100.0}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_rejects_corrupt_bar_invalid_date(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{**DAILY_BAR, "date": "not-a-date"}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_rejects_corrupt_bar_unsorted(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([
        {**DAILY_BAR, "date": "2026-06-21"},
        {**DAILY_BAR, "date": "2026-06-20"},
    ])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_rejects_intraday_bar_without_timezone(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["intraday_1h"] = _intraday_series([{**INTRADAY_BAR, "timestamp": "2026-06-20T10:00:00"}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_accepts_valid_bars(tmp_path):
    store = PriceStore(tmp_path)
    good = payload()
    good["data"]["daily"] = _daily_series([DAILY_BAR])
    good["data"]["intraday_1h"] = _intraday_series([INTRADAY_BAR])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(good))

    loaded = store.load("285A")
    assert loaded is not None
    assert loaded["data"]["daily"]["bars"][0]["date"] == "2026-06-20"


# --- NaN / Infinity / numeric validation ---

def test_load_rejects_nan_price_in_json(tmp_path):
    store = PriceStore(tmp_path)
    raw = '{"schema_version":"1.1","ticker":"285A","data":{"daily":{"status":"ok","fetched_at":"2026-06-21T12:00:00+09:00","data_as_of":"2026-06-20","bars":[{"date":"2026-06-20","open":NaN,"high":110.0,"low":90.0,"close":105.0,"volume":1000}]},"intraday_1h":{"status":"ok","fetched_at":"2026-06-21T12:00:00+09:00","data_as_of":null,"bars":[]}}}'
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(raw)
    assert store.load("285A") is None


def test_load_rejects_infinity_price_in_json(tmp_path):
    store = PriceStore(tmp_path)
    raw = '{"schema_version":"1.1","ticker":"285A","data":{"daily":{"status":"ok","fetched_at":"2026-06-21T12:00:00+09:00","data_as_of":"2026-06-20","bars":[{"date":"2026-06-20","open":Infinity,"high":110.0,"low":90.0,"close":105.0,"volume":1000}]},"intraday_1h":{"status":"ok","fetched_at":"2026-06-21T12:00:00+09:00","data_as_of":null,"bars":[]}}}'
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(raw)
    assert store.load("285A") is None


def test_load_rejects_nan_in_price_field(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{**DAILY_BAR, "open": float("nan")}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    # json.dumps by default writes NaN as NaN, but allow_nan=True is default
    # We test that validation catches it at the bar level
    path.write_text(json.dumps(bad, allow_nan=True))
    assert store.load("285A") is None


def test_load_rejects_negative_price(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{**DAILY_BAR, "close": -105.0}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))
    assert store.load("285A") is None


def test_load_rejects_zero_price(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{**DAILY_BAR, "close": 0.0}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))
    assert store.load("285A") is None


# --- OHLC consistency ---

def test_load_rejects_high_below_open(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{**DAILY_BAR, "high": 90.0, "open": 100.0, "low": 80.0, "close": 95.0}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))
    assert store.load("285A") is None


def test_load_rejects_low_above_close(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{**DAILY_BAR, "high": 120.0, "open": 100.0, "low": 110.0, "close": 105.0}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))
    assert store.load("285A") is None


# --- Volume validation ---

def test_load_rejects_negative_volume(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{**DAILY_BAR, "volume": -100}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))
    assert store.load("285A") is None


def test_load_accepts_volume_none(tmp_path):
    """volume may be None when unavailable."""
    store = PriceStore(tmp_path)
    good = payload()
    good["data"]["daily"] = _daily_series([{**DAILY_BAR, "volume": None}])
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(good))
    assert store.load("285A") is not None


# --- Metadata validation ---

def test_load_rejects_invalid_fetched_at(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = {
        "status": "ok",
        "fetched_at": "yesterday afternoon",
        "data_as_of": None,
        "bars": [],
    }
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))
    assert store.load("285A") is None


def test_load_rejects_data_as_of_mismatch_with_last_bar(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = {
        "status": "ok",
        "fetched_at": "2026-06-21T12:00:00+09:00",
        "data_as_of": "2025-01-01",  # does not match last bar date
        "bars": [DAILY_BAR],
    }
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))
    assert store.load("285A") is None


def test_load_rejects_data_as_of_present_but_bars_empty(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"] = {
        "status": "ok",
        "fetched_at": "2026-06-21T12:00:00+09:00",
        "data_as_of": "2026-06-20",
        "bars": [],
    }
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))
    assert store.load("285A") is None


# --- Save failure cleanup ---

def test_save_cleans_up_temp_file_on_failure(tmp_path):
    store = PriceStore(tmp_path)
    # Create a payload with NaN that will fail json.dump(allow_nan=False)
    bad = payload()
    bad["data"]["daily"] = _daily_series([{**DAILY_BAR, "open": float("nan")}])
    with pytest.raises(ValueError):
        store.save("285A", bad)
    assert list(tmp_path.rglob("*.tmp")) == []
