"""Regression tests for portfolio-auth cookie refresh system.

Tests that fresh SBI_COOKIE env var produces Playwright cookie objects,
that save_cookie rejects missing critical keys, that canonical storage
has metadata + fingerprint, and that the auth CLI rejects positional args.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

CORE = Path("/Users/fujie/.dotfiles/portfolio-core")
AUTH = Path("/Users/fujie/.dotfiles/claude/skills/portfolio-auth/auth_sbi.py")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw_cookie():
    return "JSESSIONID=js; __lt__sid=sid; __lt__cid=cid; AWSALBCORS=cors"


def cookie_json():
    return json.dumps([
        {"name": "JSESSIONID", "value": "js", "domain": "site1.sbisec.co.jp", "path": "/", "secure": True},
        {"name": "__lt__sid", "value": "sid", "domain": ".site1.sbisec.co.jp", "path": "/", "secure": False},
        {"name": "__lt__cid", "value": "cid", "domain": ".site1.sbisec.co.jp", "path": "/", "secure": False},
        {"name": "AWSALBCORS", "value": "cors", "domain": "site1.sbisec.co.jp", "path": "/", "secure": True},
    ])


def test_raw_env_cookie_produces_playwright_objects(monkeypatch):
    cookie_store = load_module(CORE / "cookie_store.py", "cookie_store_raw_env")
    monkeypatch.setenv("SBI_COOKIE", raw_cookie())

    cookies = cookie_store.read_cookie_objects()

    assert {c["name"] for c in cookies} >= {"JSESSIONID", "__lt__sid", "__lt__cid", "AWSALBCORS"}


def test_cookie_store_rejects_missing_login_tokens(tmp_path, monkeypatch):
    cookie_store = load_module(CORE / "cookie_store.py", "cookie_store_critical")
    monkeypatch.setattr(cookie_store, "CANONICAL_DIR", tmp_path)
    monkeypatch.setattr(cookie_store, "CANONICAL_FILE", tmp_path / "tokens.json")

    try:
        cookie_store.save_cookie("JSESSIONID=js; AWSALB=alb; AWSALBCORS=cors", source="test")
    except ValueError as e:
        assert "__lt__sid" in str(e)
        assert "__lt__cid" in str(e)
    else:
        raise AssertionError("save_cookie accepted a Cookie missing __lt__sid/__lt__cid")


def test_save_cookie_writes_metadata_and_fingerprint(tmp_path, monkeypatch):
    cookie_store = load_module(CORE / "cookie_store.py", "cookie_store_metadata")
    monkeypatch.setattr(cookie_store, "CANONICAL_DIR", tmp_path)
    monkeypatch.setattr(cookie_store, "CANONICAL_FILE", tmp_path / "tokens.json")

    cookie_store.save_cookie(cookie_json(), source="stdin")
    data = json.loads((tmp_path / "tokens.json").read_text())

    assert data["source"] == "stdin"
    assert data["saved_at"]
    assert len(data["fingerprint"]) == 12
    assert {c["name"] for c in data["cookies"]} >= {"JSESSIONID", "__lt__sid", "__lt__cid", "AWSALBCORS"}


def test_auth_cli_rejects_positional_cookie():
    result = subprocess.run(
        [sys.executable, str(AUTH), raw_cookie()],
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(CORE)},
    )

    assert result.returncode != 0
    assert "Use --save-stdin, --save-file, or SBI_COOKIE with --save" in result.stderr
