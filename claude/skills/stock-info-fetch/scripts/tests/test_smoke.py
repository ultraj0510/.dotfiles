"""Smoke test requiring real SBI authentication. Opt-in via RUN_SBI_SMOKE=1."""
import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "fetch_stock_info"


@pytest.mark.skipif(
    os.environ.get("RUN_SBI_SMOKE") != "1",
    reason="set RUN_SBI_SMOKE=1 for authenticated SBI smoke test",
)
def test_authenticated_stock_fetch_has_useful_sections_and_no_secrets():
    completed = subprocess.run(
        [str(SCRIPT), "3932", "--refresh"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["ticker"] == "3932"
    useful = [
        name
        for name, section in result["sections"].items()
        if section["status"] == "ok" and section["data"]
    ]
    assert {"price", "company_profile"}.issubset(useful)
    combined = completed.stdout + completed.stderr
    for secret_key in ("token=", "enc=", "ahash=", "hhash=", "ihash="):
        assert secret_key not in combined
