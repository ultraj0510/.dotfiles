import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


AUTH_SCRIPT = Path(__file__).resolve().parents[1] / "auth_sbi.py"


def load_auth_module():
    spec = importlib.util.spec_from_file_location("auth_sbi_under_test", AUTH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_check_resaves_valid_cookie(monkeypatch, capsys):
    module = load_auth_module()
    calls = []

    fake_cookie_store = SimpleNamespace(
        read_cookie=lambda: "JSESSIONID=x; __lt__sid=y; __lt__cid=z; AWSALBCORS=a",
        save_cookie=lambda cookie, source: calls.append((cookie, source)),
    )
    fake_sbi_auth = SimpleNamespace(
        validate=lambda cookie: ("OK", None),
    )

    monkeypatch.setitem(sys.modules, "cookie_store", fake_cookie_store)
    monkeypatch.setitem(sys.modules, "sbi_auth", fake_sbi_auth)

    module.cmd_default()
    out = capsys.readouterr().out

    assert "STATUS: OK" in out
    assert calls == [("JSESSIONID=x; __lt__sid=y; __lt__cid=z; AWSALBCORS=a", "check")]
