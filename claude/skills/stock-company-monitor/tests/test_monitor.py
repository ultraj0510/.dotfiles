import json, pytest
from pathlib import Path
from monitor import check_ticker, expire_rating, MonitorReport

def _fake_run_skill(skill_name, args):
    if skill_name == "stock-ir-fetch":
        return type("R", (), {"parsed": {"status": "partial", "documents": [
            {"document_id": "new001", "title": "業績予想の修正", "published_at": "2026-06-22", "category": "forecast_revision"},
        ], "summary": {"prohibited_documents": 0, "dynamic_pages": 0}}, "exit_code": 0})()
    return type("R", (), {"parsed": {"status": "success"}, "exit_code": 0})()

def test_check_ticker_detects_new_events(tmp_path):
    # Setup previous manifest (snapshot before fetch)
    prev_dir = tmp_path / "285A" / "raw" / "stock-ir-fetch"
    prev_dir.mkdir(parents=True)
    prev_dir.joinpath("manifest.json").write_text(json.dumps({"documents": []}))
    report = check_ticker("285A", tmp_path, _fake_run_skill)
    assert len(report.events) == 1
    assert report.events[0].event_type == "forecast_revision"

def test_check_ticker_dedup_against_ledger(tmp_path):
    prev_dir = tmp_path / "285A" / "raw" / "stock-ir-fetch"
    prev_dir.mkdir(parents=True)
    prev_dir.joinpath("manifest.json").write_text(json.dumps({"documents": []}))
    # First check creates ledger entry
    check_ticker("285A", tmp_path, _fake_run_skill)
    # Second check: same doc → dedup
    report2 = check_ticker("285A", tmp_path, _fake_run_skill)
    assert len(report2.events) == 0

def test_expire_rating_writes_expiry(tmp_path):
    latest = tmp_path / "285A" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps({"latest_run_id": "r1", "latest_status": "completed", "latest_rating": "HOLD"}))
    expire_rating("285A", tmp_path, "forecast_revision: test")
    data = json.loads(latest.read_text())
    assert data["latest_status"] == "expired"
    assert "forecast_revision" in data["expired_reason"]

def test_monitor_report_aggregates():
    r = MonitorReport("2026-06-22T17:00:00+09:00", 2, 1, 0, 0, [])
    assert r.tickers_checked == 2
    assert r.events_found == 1

def test_weekday_gate_skips_weekend(tmp_path, monkeypatch):
    from monitor import monitor
    from watchlist import add_to_watchlist
    add_to_watchlist("285A", tmp_path)
    saturday = __import__('datetime').datetime(2026, 6, 27, 17, 0, tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Tokyo'))
    monkeypatch.setattr("monitor.datetime", type("M", (), {"now": lambda tz=None: saturday}))
    report = monitor(tmp_path, auto_reanalyze=False)
    assert report.tickers_checked == 0  # Weekend skip
