import json, pytest
from lock_manager import acquire_lock, release_lock, is_stale_lock

def test_acquire_success(tmp_path):
    r = acquire_lock("285A", "run-001", tmp_path)
    assert r.acquired is True

def test_acquire_rejects_duplicate(tmp_path):
    acquire_lock("285A", "run-001", tmp_path)
    r = acquire_lock("285A", "run-002", tmp_path)
    assert r.acquired is False
    assert r.existing_run_id == "run-001"

def test_different_tickers_ok(tmp_path):
    assert acquire_lock("285A", "run-001", tmp_path).acquired
    assert acquire_lock("3932", "run-002", tmp_path).acquired

def test_release_then_reacquire(tmp_path):
    acquire_lock("285A", "run-001", tmp_path)
    release_lock("285A", tmp_path)
    assert acquire_lock("285A", "run-002", tmp_path).acquired

def test_stale_lock_cleanup(tmp_path):
    acquire_lock("285A", "run-old", tmp_path)
    lp = tmp_path / "285A" / "analysis.lock"
    d = json.loads(lp.read_text())
    d["pid"] = 0
    d["expires_at"] = "2020-01-01T00:00:00+09:00"
    lp.write_text(json.dumps(d))
    assert is_stale_lock(lp) is True
    assert acquire_lock("285A", "run-new", tmp_path, force_stale=True).acquired
