"""Smoke test requiring real SBI authentication. Opt-in via RUN_SBI_SMOKE=1."""
import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "fetch_stock_info"

EXPECTED_SECTIONS = {
    "price", "company_profile", "company_scores",
    "performance", "news", "disclosures", "stock_reports",
}
VALID_STATUSES = {"ok", "not_available", "error"}
SENSITIVE_PARAMS = {"token", "enc", "ahash", "hhash", "ihash"}


@pytest.mark.skipif(
    os.environ.get("RUN_SBI_SMOKE") != "1",
    reason="set RUN_SBI_SMOKE=1 for authenticated SBI smoke test",
)
def test_authenticated_smoke_all_7_sections():
    completed = subprocess.run(
        [str(SCRIPT), "3932", "--refresh"],
        text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, f"stderr: {completed.stderr}"
    result = json.loads(completed.stdout)

    assert result["schema_version"] == "1.0"
    assert result["ticker"] == "3932"
    assert isinstance(result["company_name"], str)
    sections = result["sections"]
    assert isinstance(sections, dict)
    assert set(sections.keys()) == EXPECTED_SECTIONS, (
        f"Missing sections: {EXPECTED_SECTIONS - set(sections.keys())}"
    )

    for name, section in sections.items():
        assert section["status"] in VALID_STATUSES
        assert "data" in section
        assert "source" in section

    errors = result.get("errors", [])
    for err in errors:
        assert err["section"] in list(EXPECTED_SECTIONS) + ["_global"]

    # No secrets in stdout, stderr, or fetched URLs
    combined = completed.stdout + completed.stderr
    for param in SENSITIVE_PARAMS:
        assert f"{param}=" not in combined, f"secret {param} leaked"

    # Verify cache was written correctly
    cache_dir = Path.home() / ".claude" / "cache" / "stock-info-fetch"
    cache_file = cache_dir / "3932.json"
    assert cache_file.exists(), "cache file was not created"
    cached = json.loads(cache_file.read_text())
    assert cached["schema_version"] == "1.0"
    cached_sections = cached.get("sections", {})
    assert isinstance(cached_sections, dict)
    assert set(cached_sections.keys()) == EXPECTED_SECTIONS
    for param in SENSITIVE_PARAMS:
        assert f"{param}=" not in json.dumps(cached, ensure_ascii=False)
