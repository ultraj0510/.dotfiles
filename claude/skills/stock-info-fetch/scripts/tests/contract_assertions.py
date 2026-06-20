"""Shared contract assertions for stock-info-fetch output validation."""
import json

EXPECTED_SECTIONS = {
    "price", "company_profile", "company_scores",
    "performance", "news", "disclosures", "stock_reports",
}
VALID_STATUSES = {"ok", "not_available", "error"}
SENSITIVE_PARAMS = {"token", "enc", "ahash", "hhash", "ihash"}


def assert_stock_info_contract(payload, expected_ticker="3932", require_useful=False):
    """Verify JSON output contract. When require_useful=True, assert
    price and company_profile have real data."""
    assert payload["schema_version"] == "1.0"
    assert payload["ticker"] == expected_ticker
    assert isinstance(payload["company_name"], str)
    sections = payload["sections"]
    assert isinstance(sections, dict)
    assert set(sections.keys()) == EXPECTED_SECTIONS, (
        f"Missing: {EXPECTED_SECTIONS - set(sections.keys())}"
    )
    for name, section in sections.items():
        assert isinstance(section, dict), f"{name} not a dict"
        assert section["status"] in VALID_STATUSES, f"{name} status={section['status']}"
        assert "data" in section
        assert "source" in section
        assert isinstance(section["source"], dict)
        assert isinstance(section["source"].get("url"), str), f"{name} source.url missing"

    # Secret params must not leak
    payload_str = json.dumps(payload, ensure_ascii=False)
    for param in SENSITIVE_PARAMS:
        assert f"{param}=" not in payload_str, f"secret {param} leaked"

    errors = payload.get("errors", [])
    assert isinstance(errors, list)
    for err in errors:
        assert "section" in err
        assert "code" in err
        assert "message" in err

    if require_useful:
        assert payload["sections"]["price"]["status"] == "ok", "price not ok"
        assert payload["sections"]["price"]["data"].get("current_price", 0) > 0
        assert payload["sections"]["price"]["data"].get("quote_timestamp")
        assert payload["sections"]["company_profile"]["status"] == "ok", "profile not ok"
        assert payload["sections"]["company_profile"]["data"].get("company_name")
        # Error sections must have corresponding error entries
        for name, section in payload["sections"].items():
            if section["status"] == "error":
                assert any(e["section"] == name for e in payload["errors"]), (
                    f"{name} is error but no matching error entry"
                )
