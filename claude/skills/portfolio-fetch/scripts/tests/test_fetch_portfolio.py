import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parents[1]
WRAPPER = SCRIPT_DIR / "fetch_portfolio"
PY_SCRIPT = SCRIPT_DIR / "fetch_portfolio.py"


def load_fetch_module():
    spec = importlib.util.spec_from_file_location("portfolio_fetch_under_test", PY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_wrapper_prefers_stock_price_analyze_venv_before_stock_advisor():
    import subprocess
    result = subprocess.run([str(WRAPPER), "--print-python"], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    selected = result.stdout.strip()
    assert selected.startswith(str(Path.home() / "code/playground/stock-price-analyze"))
    assert "stock-advisor" not in selected


def test_default_fetch_prints_json_and_updates_status(monkeypatch, capsys, tmp_path):
    module = load_fetch_module()
    snapshot = {
        "fetched_at": "2026-06-17T00:00:00+00:00",
        "source": "SBI",
        "sync_status": "ok",
        "cache_used": False,
        "account": {"total_assets": 1000000.0},
        "holdings": [{"ticker": "7974.T", "name": "任天堂"}],
    }
    fake_sbi_fetch = SimpleNamespace(fetch_raw_snapshot=lambda path: (snapshot, "ok"))
    monkeypatch.setitem(sys.modules, "sbi_fetch", fake_sbi_fetch)
    monkeypatch.setattr(module, "_DEFAULT_PORTFOLIO_PATH", str(tmp_path / "portfolio.yaml"))
    monkeypatch.setattr(sys, "argv", ["fetch_portfolio.py"])

    module.main()
    out = capsys.readouterr().out

    assert json.loads(out) == snapshot


def test_skip_sync_prints_cached_json(monkeypatch, capsys, tmp_path):
    module = load_fetch_module()
    snapshot = {
        "fetched_at": "2026-06-16T00:00:00+00:00",
        "source": "SBI",
        "sync_status": "cache",
        "cache_used": True,
        "account": {},
        "holdings": [],
    }
    fake_sbi_fetch = SimpleNamespace(load_cached_snapshot=lambda path, status="cache": snapshot)
    monkeypatch.setitem(sys.modules, "sbi_fetch", fake_sbi_fetch)
    monkeypatch.setattr(module, "_DEFAULT_PORTFOLIO_PATH", str(tmp_path / "portfolio.yaml"))
    monkeypatch.setattr(sys, "argv", ["fetch_portfolio.py", "--skip-sync"])

    module.main()
    out = capsys.readouterr().out

    assert json.loads(out)["cache_used"] is True
    assert json.loads(out)["sync_status"] == "cache"


def test_auth_expired_exits_2(monkeypatch, capsys, tmp_path):
    module = load_fetch_module()
    fake_sbi_fetch = SimpleNamespace(fetch_raw_snapshot=lambda path: ({}, "auth_expired"))
    monkeypatch.setitem(sys.modules, "sbi_fetch", fake_sbi_fetch)
    monkeypatch.setattr(module, "_DEFAULT_PORTFOLIO_PATH", str(tmp_path / "portfolio.yaml"))
    monkeypatch.setattr(sys, "argv", ["fetch_portfolio.py"])

    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected SystemExit")

    assert "[AUTH_EXPIRED]" in capsys.readouterr().err
