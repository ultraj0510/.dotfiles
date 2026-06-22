import json, pytest
from watchlist import load_watchlist, add_to_watchlist, remove_from_watchlist, update_last_checked

def test_load_empty(tmp_path):
    assert load_watchlist(tmp_path) == []

def test_add_and_load(tmp_path):
    add_to_watchlist("285A", tmp_path)
    wl = load_watchlist(tmp_path)
    assert len(wl) == 1
    assert wl[0]["ticker"] == "285A"

def test_add_duplicate_ignored(tmp_path):
    add_to_watchlist("285A", tmp_path)
    add_to_watchlist("285A", tmp_path)
    assert len(load_watchlist(tmp_path)) == 1

def test_remove(tmp_path):
    add_to_watchlist("285A", tmp_path)
    add_to_watchlist("3932", tmp_path)
    remove_from_watchlist("285A", tmp_path)
    assert len(load_watchlist(tmp_path)) == 1

def test_update_last_checked(tmp_path):
    add_to_watchlist("285A", tmp_path)
    update_last_checked("285A", tmp_path, "2026-06-22T17:00:00+09:00")
    assert load_watchlist(tmp_path)[0]["last_checked_at"] == "2026-06-22T17:00:00+09:00"
