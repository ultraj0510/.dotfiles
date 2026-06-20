import json

from price_store import PriceStore


def payload(ticker="285A"):
    return {
        "schema_version": "1.0",
        "ticker": ticker,
        "data": {"daily": [], "intraday_1h": []},
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


def test_save_replaces_existing_file_without_tmp_residue(tmp_path):
    store = PriceStore(tmp_path)
    store.save("285A", payload())
    updated = payload()
    updated["data"]["daily"] = [{"date": "2026-06-20"}]

    store.save("285A", updated)

    assert store.load("285A")["data"]["daily"] == [{"date": "2026-06-20"}]
    assert list(tmp_path.rglob("*.tmp")) == []
