import pytest
from event_detector import detect_events

def test_detect_new_earnings_revision():
    prev = {"documents": []}
    curr = {"documents": [{"title": "業績予想の修正に関するお知らせ", "published_at": "2026-06-22", "document_id": "abc", "category": "forecast_revision"}]}
    events = detect_events(prev, curr, None)
    assert len(events) == 1
    assert events[0].event_type == "forecast_revision"

def test_no_event_when_no_new_docs():
    prev = {"documents": [{"document_id": "abc", "title": "old"}]}
    curr = {"documents": [{"document_id": "abc", "title": "old"}]}
    assert len(detect_events(prev, curr, None)) == 0

def test_detect_dividend_revision():
    prev = {"documents": []}
    curr = {"documents": [{"title": "配当予想の修正に関するお知らせ", "published_at": "2026-06-22", "document_id": "ghi", "category": "forecast_revision"}]}
    assert detect_events(prev, curr, None)[0].event_type == "dividend_revision"

def test_multiple_new_events():
    prev = {"documents": []}
    curr = {"documents": [
        {"document_id": "a", "title": "業績予想の修正", "published_at": "2026-06-22", "category": "forecast_revision"},
        {"document_id": "b", "title": "自己株式の取得", "published_at": "2026-06-22", "category": "material_disclosure"},
    ]}
    assert len(detect_events(prev, curr, None)) == 2
