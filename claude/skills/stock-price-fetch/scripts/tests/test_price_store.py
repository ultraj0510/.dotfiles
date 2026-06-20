import json

from price_store import PriceStore


def _daily_series(bars=None):
    return {"status": "ok", "fetched_at": "2026-06-21T12:00:00+09:00", "data_as_of": "2026-06-20", "bars": bars or []}

def _intraday_series(bars=None):
    return {"status": "ok", "fetched_at": "2026-06-21T12:00:00+09:00", "data_as_of": "2026-06-21T10:00:00+09:00", "bars": bars or []}


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
    updated["data"]["daily"]["bars"] = [{"date": "2026-06-20", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000}]

    store.save("285A", updated)

    loaded = store.load("285A")
    assert loaded["data"]["daily"]["bars"] == [{"date": "2026-06-20", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000}]
    assert list(tmp_path.rglob("*.tmp")) == []


def test_load_rejects_corrupt_bar_missing_keys(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"]["bars"] = [{"date": "2026-06-20", "open": 100.0}]
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_rejects_corrupt_bar_invalid_date(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"]["bars"] = [{"date": "not-a-date", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000}]
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_rejects_corrupt_bar_unsorted(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["daily"]["bars"] = [
        {"date": "2026-06-21", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000},
        {"date": "2026-06-20", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000},
    ]
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_rejects_intraday_bar_without_timezone(tmp_path):
    store = PriceStore(tmp_path)
    bad = payload()
    bad["data"]["intraday_1h"]["bars"] = [{"timestamp": "2026-06-20T10:00:00", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000}]
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bad))

    assert store.load("285A") is None


def test_load_accepts_valid_bars(tmp_path):
    store = PriceStore(tmp_path)
    good = payload()
    good["data"]["daily"]["bars"] = [{"date": "2026-06-20", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000}]
    good["data"]["intraday_1h"]["bars"] = [{"timestamp": "2026-06-20T10:00:00+09:00", "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000}]
    path = store.path_for("285A")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(good))

    loaded = store.load("285A")
    assert loaded is not None
    assert loaded["data"]["daily"]["bars"][0]["date"] == "2026-06-20"
