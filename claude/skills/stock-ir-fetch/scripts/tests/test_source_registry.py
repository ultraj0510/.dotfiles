import json
from datetime import datetime
from zoneinfo import ZoneInfo

from source_registry import SourceRegistry

JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 6, 21, 12, 0, tzinfo=JST)

VALID_CANDIDATE = {
    "candidate_id": "abc123def4567890abcd",
    "company_name": "Test Inc.",
    "company_site_url": "https://example.co.jp/",
    "ir_top_url": "https://example.co.jp/ir/",
    "document_index_url": "https://example.co.jp/ir/library/",
    "approved_domain": "example.co.jp",
}


def test_approve_writes_validated_candidate(tmp_path):
    registry = SourceRegistry(tmp_path)
    source = registry.approve("285A", VALID_CANDIDATE, NOW)
    assert source["approval_method"] == "user"
    assert registry.load("285A") == source


def test_load_rejects_wrong_ticker(tmp_path):
    registry = SourceRegistry(tmp_path)
    registry.approve("3932", VALID_CANDIDATE, NOW)
    assert registry.load("285A") is None


def test_load_rejects_unknown_schema(tmp_path):
    registry = SourceRegistry(tmp_path)
    path = registry.path_for("285A")
    path.parent.mkdir(parents=True)
    bad = {**VALID_CANDIDATE, "schema_version": "2.0", "ticker": "285A",
           "approved_at": NOW.isoformat(), "last_verified_at": NOW.isoformat(),
           "last_successful_sync_at": None, "approval_method": "user",
           "ir_top_url": "https://example.co.jp/ir/",
           "document_index_url": "https://example.co.jp/ir/library/",
           "company_site_url": "https://example.co.jp/"}
    path.write_text(json.dumps(bad))
    assert registry.load("285A") is None


def test_load_rejects_non_https_url(tmp_path):
    registry = SourceRegistry(tmp_path)
    path = registry.path_for("285A")
    path.parent.mkdir(parents=True)
    bad = _source_with_urls(ir_top="http://example.co.jp/ir/")
    path.write_text(json.dumps(bad))
    assert registry.load("285A") is None


def test_update_sync_times(tmp_path):
    registry = SourceRegistry(tmp_path)
    registry.approve("285A", VALID_CANDIDATE, NOW)
    later = datetime(2026, 6, 22, 12, 0, tzinfo=JST)
    updated = registry.update_sync_times("285A", later, later)
    assert updated["last_verified_at"] == later.isoformat()
    assert updated["last_successful_sync_at"] == later.isoformat()


def test_save_cleans_temp_file_on_failure(tmp_path):
    registry = SourceRegistry(tmp_path)
    path = registry.path_for("285A")
    path.parent.mkdir(parents=True)
    try:
        registry._save("285A", {"bad": float("nan")})
    except ValueError:
        pass
    assert list(tmp_path.rglob("*.tmp")) == []


def _source_with_urls(ir_top="https://example.co.jp/ir/"):
    return {
        "schema_version": "1.0", "ticker": "285A",
        "company_name": "Test", "company_site_url": "https://example.co.jp/",
        "ir_top_url": ir_top,
        "document_index_url": "https://example.co.jp/ir/library/",
        "approved_domain": "example.co.jp",
        "approved_at": NOW.isoformat(), "last_verified_at": NOW.isoformat(),
        "last_successful_sync_at": None, "approval_method": "user",
    }
