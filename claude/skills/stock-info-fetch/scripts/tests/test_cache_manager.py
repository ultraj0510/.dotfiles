"""Tests for cache_manager module."""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cache_manager import CacheManager

JST = timezone(timedelta(hours=9))


def test_cache_miss_on_empty_dir(tmp_path):
    cm = CacheManager(cache_dir=tmp_path)
    result = cm.get("3932")
    assert result is None


def test_cache_hit_same_day(tmp_path):
    cm = CacheManager(cache_dir=tmp_path)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    sections = {
        "price": {"status": "ok", "data": {}},
        "company_profile": {"status": "ok", "data": {}},
        "company_scores": {"status": "ok", "data": {}},
        "performance": {"status": "ok", "data": {}},
        "news": {"status": "ok", "data": []},
        "disclosures": {"status": "ok", "data": []},
        "stock_reports": {"status": "ok", "data": {}},
    }
    data = {"schema_version": "1.0", "ticker": "3932", "cache": {"hit": False, "date": today}, "sections": sections}
    cm.save("3932", data)

    result = cm.get("3932")
    assert result is not None
    assert result["ticker"] == "3932"
    assert result["cache"]["hit"] is True
    assert result["cache"]["date"] == today


def test_cache_miss_different_day(tmp_path):
    cm = CacheManager(cache_dir=tmp_path)
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
    data = {
        "ticker": "3932",
        "cache": {"hit": False, "date": yesterday},
    }
    # Write directly to avoid save() overwriting the date to today
    cache_file = tmp_path / "3932.json"
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    result = cm.get("3932")
    assert result is None


def test_refresh_bypasses_cache(tmp_path):
    cm = CacheManager(cache_dir=tmp_path)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    data = {"ticker": "3932", "cache": {"hit": False, "date": today}}
    cm.save("3932", data)

    result = cm.get("3932", refresh=True)
    assert result is None


def test_atomic_write_does_not_leave_temp_file(tmp_path):
    cm = CacheManager(cache_dir=tmp_path)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    cm.save("3932", {"ticker": "3932", "cache": {"hit": False, "date": today}})

    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_cache_file_is_owner_only(tmp_path):
    cm = CacheManager(cache_dir=tmp_path)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    cm.save("3932", {"ticker": "3932", "cache": {"hit": False, "date": today}})
    assert (tmp_path / "3932.json").stat().st_mode & 0o777 == 0o600


def test_cache_key_includes_ticker(tmp_path):
    cm = CacheManager(cache_dir=tmp_path)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    sections = {
        "price": {"status": "ok", "data": {}},
        "company_profile": {"status": "ok", "data": {}},
        "company_scores": {"status": "ok", "data": {}},
        "performance": {"status": "ok", "data": {}},
        "news": {"status": "ok", "data": []},
        "disclosures": {"status": "ok", "data": []},
        "stock_reports": {"status": "ok", "data": {}},
    }
    cm.save("3932", {"schema_version": "1.0", "ticker": "3932", "cache": {"hit": False, "date": today}, "sections": sections})
    cm.save("7203", {"schema_version": "1.0", "ticker": "7203", "cache": {"hit": False, "date": today}, "sections": sections})

    r1 = cm.get("3932")
    r2 = cm.get("7203")
    assert r1["ticker"] == "3932"
    assert r2["ticker"] == "7203"


def test_corrupted_cache_returns_none(tmp_path):
    cm = CacheManager(cache_dir=tmp_path)
    cache_file = tmp_path / "3932.json"
    cache_file.write_text("not valid json{{{")

    result = cm.get("3932")
    assert result is None


TODAY = datetime.now(JST).strftime("%Y-%m-%d")


@pytest.mark.parametrize("data", [
    {"schema_version": "0.1", "cache": {"date": TODAY}},
    {"schema_version": "1.0", "cache": {"date": TODAY}, "sections": "not_a_dict"},
    {"schema_version": "1.0", "cache": {"date": TODAY}, "sections": {"price": {"status": "invalid_status"}}},
])
def test_invalid_cache_contract_is_miss(tmp_path, data):
    """Cache with wrong schema, missing sections dict, or invalid status must miss."""
    cm = CacheManager(cache_dir=tmp_path)
    cache_file = tmp_path / "3932.json"
    cache_file.write_text(json.dumps(data, ensure_ascii=False))
    result = cm.get("3932")
    assert result is None


def test_valid_cache_with_all_sections_hits(tmp_path):
    """Valid schema 1.0 with 7 sections and valid statuses must hit."""
    data = {
        "schema_version": "1.0",
        "ticker": "3932",
        "cache": {"hit": False, "date": TODAY},
        "sections": {
            "price": {"status": "ok", "data": {}},
            "company_profile": {"status": "ok", "data": {}},
            "company_scores": {"status": "not_available", "data": {}},
            "performance": {"status": "ok", "data": {}},
            "news": {"status": "error", "data": []},
            "disclosures": {"status": "ok", "data": []},
            "stock_reports": {"status": "not_available", "data": {}},
        },
    }
    cm = CacheManager(cache_dir=tmp_path)
    cm.save("3932", data)
    result = cm.get("3932")
    assert result is not None
    assert result["ticker"] == "3932"
    assert result["cache"]["hit"] is True


def test_concurrent_save_does_not_corrupt_cache(tmp_path):
    """Simultaneous saves must not leave corrupt or partial files."""
    import threading
    errors = []
    cm = CacheManager(cache_dir=tmp_path)
    def save_data(n):
        try:
            data = {
                "schema_version": "1.0",
                "ticker": "3932",
                "cache": {"hit": False, "date": TODAY},
                "sections": {
                    "price": {"status": "ok", "data": {"n": n}},
                    "company_profile": {"status": "ok", "data": {}},
                    "company_scores": {"status": "ok", "data": {}},
                    "performance": {"status": "ok", "data": {}},
                    "news": {"status": "ok", "data": []},
                    "disclosures": {"status": "ok", "data": []},
                    "stock_reports": {"status": "ok", "data": {}},
                },
            }
            cm.save("3932", data)
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=save_data, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(errors) == 0
    # Cache file must be valid JSON
    result = cm.get("3932")
    assert result is not None
    # No leftover tmp files
    assert len(list(tmp_path.glob("*.tmp"))) == 0
