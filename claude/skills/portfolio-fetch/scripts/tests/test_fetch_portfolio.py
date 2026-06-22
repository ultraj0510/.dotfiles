import importlib.util
import json
import sys
import yaml
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
    portfolio_path = tmp_path / "portfolio.yaml"
    now_iso = "2026-06-19T00:00:00+00:00"
    portfolio_data = {
        "last_updated": now_iso,
        "last_sync_source": "SBI",
        "sync_status": "ok",
        "account": {"total_assets": 1000000.0},
        "holdings": [{"ticker": "7974.T", "name": "任天堂"}],
    }
    with open(portfolio_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(portfolio_data, f, allow_unicode=True)

    fake_sbi_fetch = SimpleNamespace(sync_from_sbi=lambda path: "ok")
    monkeypatch.setitem(sys.modules, "sbi_fetch", fake_sbi_fetch)
    monkeypatch.setattr(module, "_DEFAULT_PORTFOLIO_PATH", str(portfolio_path))
    monkeypatch.setattr(sys, "argv", ["fetch_portfolio.py"])

    module.main()
    out = capsys.readouterr().out

    result = json.loads(out)
    assert result["fetched_at"] == now_iso
    assert result["source"] == "SBI"
    assert result["sync_status"] == "ok"
    assert result["cache_used"] is False
    assert result["account"] == {"total_assets": 1000000.0}
    assert result["holdings"] == [{"ticker": "7974.T", "name": "任天堂"}]


def test_skip_sync_prints_cached_json(monkeypatch, capsys, tmp_path):
    module = load_fetch_module()
    portfolio_path = tmp_path / "portfolio.yaml"
    portfolio_data = {
        "last_updated": "2026-06-16T00:00:00+00:00",
        "last_sync_source": "SBI",
        "sync_status": "cache",
        "account": {},
        "holdings": [],
    }
    with open(portfolio_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(portfolio_data, f, allow_unicode=True)

    monkeypatch.setattr(module, "_DEFAULT_PORTFOLIO_PATH", str(portfolio_path))
    monkeypatch.setattr(sys, "argv", ["fetch_portfolio.py", "--skip-sync"])

    module.main()
    out = capsys.readouterr().out

    result = json.loads(out)
    assert result["cache_used"] is True
    assert result["sync_status"] == "cache"
    assert result["fetched_at"] == "2026-06-16T00:00:00+00:00"
    assert result["source"] == "SBI"


def test_auth_expired_exits_2(monkeypatch, capsys, tmp_path):
    module = load_fetch_module()
    fake_sbi_fetch = SimpleNamespace(sync_from_sbi=lambda path: "auth_expired")
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


def test_use_cache_on_fail_falls_back_to_cache(monkeypatch, capsys, tmp_path):
    module = load_fetch_module()
    portfolio_path = tmp_path / "portfolio.yaml"
    portfolio_data = {
        "last_updated": "2026-06-15T00:00:00+00:00",
        "last_sync_source": "SBI",
        "sync_status": "cache",
        "account": {"total_assets": 500000.0},
        "holdings": [{"ticker": "8473.T", "name": "ＳＢＩ"}],
    }
    with open(portfolio_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(portfolio_data, f, allow_unicode=True)

    fake_sbi_fetch = SimpleNamespace(sync_from_sbi=lambda path: "network_error")
    monkeypatch.setitem(sys.modules, "sbi_fetch", fake_sbi_fetch)
    monkeypatch.setattr(module, "_DEFAULT_PORTFOLIO_PATH", str(portfolio_path))
    monkeypatch.setattr(sys, "argv", ["fetch_portfolio.py", "--use-cache-on-fail"])

    module.main()
    captured = capsys.readouterr()
    out = captured.out
    err = captured.err

    result = json.loads(out)
    assert result["cache_used"] is True
    assert result["sync_status"] == "network_error"
    assert result["account"] == {"total_assets": 500000.0}
    assert "[NOTICE]" in err
