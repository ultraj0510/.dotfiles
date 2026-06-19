"""Shared test fixtures for stock-info-fetch tests."""
import sys
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def load_module(name, path):
    """Dynamically load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_cookie_store(monkeypatch):
    """Mock cookie_store module with a valid session cookie."""
    fake = SimpleNamespace()
    fake.read_cookie_bundle = lambda: {
        "cookie_header": "session_a=value_a; session_b=value_b",
        "cookie_objects": [
            {"name": "session_a", "value": "value_a", "domain": ".sbisec.co.jp", "path": "/"},
            {"name": "session_b", "value": "value_b", "domain": ".sbisec.co.jp", "path": "/"},
        ],
        "source": "canonical",
        "fingerprint": "synthetic0001",
        "saved_at": "2026-06-19T00:00:00+00:00",
    }
    monkeypatch.setitem(sys.modules, "cookie_store", fake)
    return fake


@pytest.fixture
def fake_cookie_store_expired(monkeypatch):
    """Mock cookie_store with no cookie (auth unset)."""
    fake = SimpleNamespace()
    fake.read_cookie_bundle = lambda: {
        "cookie_header": "",
        "cookie_objects": [],
        "source": "none",
        "fingerprint": "",
        "saved_at": None,
    }
    monkeypatch.setitem(sys.modules, "cookie_store", fake)
    return fake
