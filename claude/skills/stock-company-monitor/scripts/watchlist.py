"""Watchlist registry for monitored tickers."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def _path(data_dir):
    return Path(data_dir) / "watchlist.json"


def load_watchlist(data_dir):
    path = _path(data_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if data.get("schema_version") != "1.0":
            return []
        return data.get("tickers", [])
    except (json.JSONDecodeError, KeyError):
        return []


def _save(data_dir, tickers):
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "1.0", "tickers": tickers}, ensure_ascii=False, indent=2))


def add_to_watchlist(ticker, data_dir):
    wl = load_watchlist(data_dir)
    if any(t["ticker"] == ticker for t in wl):
        return
    wl.append({"ticker": ticker, "registered_at": datetime.now(JST).isoformat(),
               "last_checked_at": None, "last_event_at": None, "last_event_doc_ids": []})
    _save(data_dir, wl)


def remove_from_watchlist(ticker, data_dir):
    wl = [t for t in load_watchlist(data_dir) if t["ticker"] != ticker]
    _save(data_dir, wl)


def update_last_checked(ticker, data_dir, checked_at):
    wl = load_watchlist(data_dir)
    for t in wl:
        if t["ticker"] == ticker:
            t["last_checked_at"] = checked_at
    _save(data_dir, wl)


def update_last_event(ticker, data_dir, event_at, doc_ids):
    wl = load_watchlist(data_dir)
    for t in wl:
        if t["ticker"] == ticker:
            t["last_event_at"] = event_at
            t["last_event_doc_ids"] = doc_ids
    _save(data_dir, wl)
