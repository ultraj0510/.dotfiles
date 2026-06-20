"""Integration tests for the stock-info-fetch orchestrator."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


EXPECTED_SECTIONS = {
    "price", "company_profile", "company_scores",
    "performance", "news", "disclosures", "stock_reports",
}
VALID_STATUSES = {"ok", "not_available", "error"}
SENSITIVE_PARAMS = {"token", "enc", "ahash", "hhash", "ihash"}


def assert_valid_stock_info(payload, expected_ticker="3932"):
    """Verify JSON output contract."""
    assert payload["schema_version"] == "1.0"
    assert payload["ticker"] == expected_ticker
    assert isinstance(payload["company_name"], str)
    sections = payload["sections"]
    assert isinstance(sections, dict)
    assert set(sections.keys()) == EXPECTED_SECTIONS
    for name, section in sections.items():
        assert isinstance(section, dict), f"{name} section is not a dict"
        assert section["status"] in VALID_STATUSES, f"{name} status={section['status']}"
        assert "data" in section
        assert "source" in section
        assert "url" in section["source"]
        for param in SENSITIVE_PARAMS:
            assert param not in section["source"]["url"], f"{param} in {name} url"

    # Secret values must not appear in entire payload
    payload_str = json.dumps(payload, ensure_ascii=False)
    for param in SENSITIVE_PARAMS:
        assert f"{param}=" not in payload_str, f"{param} leaked in output"

    errors = payload.get("errors", [])
    assert isinstance(errors, list)
    for err in errors:
        assert "section" in err
        assert "code" in err
        assert "message" in err


def _set_fake_cookie(monkeypatch):
    fake = SimpleNamespace()
    fake.read_cookie_bundle = lambda: {
        "cookie_header": "session_a=value_a; session_b=value_b",
        "cookie_objects": [],
        "source": "canonical",
        "fingerprint": "abc",
    }
    monkeypatch.setitem(sys.modules, "cookie_store", fake)


def _set_fake_expired_cookie(monkeypatch):
    fake = SimpleNamespace()
    fake.read_cookie_bundle = lambda: {"cookie_header": "", "cookie_objects": [], "source": "none", "fingerprint": ""}
    monkeypatch.setitem(sys.modules, "cookie_store", fake)


def _set_mocks(monkeypatch, ClientClass, cache_get=None, cache_save=None):
    monkeypatch.setattr("fetch_stock_info.SafeHttpClient", ClientClass)
    fake_cache = SimpleNamespace()
    fake_cache.get = cache_get or (lambda ticker, refresh=False: None)
    fake_cache.save = cache_save or (lambda ticker, data: None)
    import fetch_stock_info as fsi
    monkeypatch.setattr(fsi, "CacheManager", lambda *args, **kw: fake_cache)
    # mock pdf_parser
    fake_pdf = SimpleNamespace()
    fake_pdf.parse_stock_report_pdf = lambda path: {"status": "not_available", "data": {}}
    monkeypatch.setitem(sys.modules, "pdf_parser", fake_pdf)


class AuthExpiredHttpClient:
    """HTTP client returns auth_expired status directly (login redirect)."""
    def fetch_html(self, url, cookie_header=""):
        return SimpleNamespace(body=None, status="auth_expired", url="https://login.sbisec.co.jp/ETGate/")


def test_auth_expired_http_status_is_global_and_not_cached(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    saved = []
    _set_mocks(monkeypatch, AuthExpiredHttpClient, cache_save=lambda ticker, data: saved.append(data))
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "auth_expired"
    assert result["sections"] == {}
    assert saved == []


class OkPriceOnlyClient:
    def fetch_html(self, url, cookie_header=""):
        if "Idtl10" in url:
            return SimpleNamespace(body=b"<table><tr><th>Current price</th><td>2,150.5</td></tr></table>", status="ok", url=url)
        return SimpleNamespace(body=b"", status="ok", url=url)


class AuthExpiredClient:
    def fetch_html(self, url, cookie_header=""):
        return SimpleNamespace(body="<form action='/login'><input type='password'><input name='userid'></form>".encode("utf-8"), status="ok", url="https://site1.sbisec.co.jp/ETGate/")


class TickerNotFoundClient:
    def fetch_html(self, url, cookie_header=""):
        return SimpleNamespace(body="該当する銘柄はありません".encode("utf-8"), status="ok", url=url)


class AuthExpiredJPClient:
    def fetch_html(self, url, cookie_header=""):
        return SimpleNamespace(body="<form action='/login'><input type='password'><input id='user_id'></form>".encode("utf-8"), status="ok", url="https://site1.sbisec.co.jp/ETGate/")


class TickerNotFoundJPClient:
    def fetch_html(self, url, cookie_header=""):
        return SimpleNamespace(body="該当する銘柄はありません".encode("utf-8"), status="ok", url=url)


class PartialClient:
    def fetch_html(self, url, cookie_header=""):
        if "Idtl10" in url:
            return SimpleNamespace(body=("<table><tr><th>現在値</th><td>2,150.5<span>06/19 14:30</span></td></tr></table>").encode("utf-8"), status="ok", url=url)
        return SimpleNamespace(body=None, status="fetch_failed", url=url)


class FullClient:
    def __init__(self):
        self.fetch_bytes_called = False

    def fetch_html(self, url, cookie_header=""):
        if "Idtl10" in url:
            body = ("<table><tr><th>現在値</th><td>2,150.5<span>06/19 14:30</span></td></tr></table>").encode("utf-8")
        elif "Idtl20" in url:
            body = ("<table><tr><td>2026/06/19 14:30</td><td>IRニュース</td><td><a href='/news/123'>記事</a></td></tr></table>").encode("utf-8")
        elif "Idtl50" in url:
            body = ("<div>作成日: 2026年06月17日\n3932 (株)Test [ 情報・通信 ]\n【特色】IT企業\n【業種】 通信サービス 時価総額順位 18/103社</div>").encode("utf-8")
        elif "Idtl70" in url:
            body = ("""<iframe src="https://graph.sbisec.co.jp/sbiscreener/analysis?pid=123&sym=3932.T"></iframe>
<a onclick="window.open('/ETGate/?sw_param1=report_summary&stock_sec_code_mul=3932','report_summary')">業績</a>
<a onclick="window.open('/ETGate/?sw_param1=report_disclose&stock_sec_code_mul=3932','report_disclose')">適時開示</a>""").encode("utf-8")
        elif "graph.sbisec.co.jp" in url:
            body = ("<table><tr><th>企業スコア総合</th><td>6.0</td></tr></table>").encode("utf-8")
        elif "report_summary" in url:
            body = ("<table><tr><th>2027/03 コンセンサス予想</th><td>240</td><td>--</td><td>--</td><td>11,000</td></tr></table>").encode("utf-8")
        elif "report_disclose" in url:
            body = ("<table><tr><td>2026/06/19 15:00</td><td>決算短信</td><td><a href='/disclosure/a.pdf'>開示</a></td></tr></table>").encode("utf-8")
        else:
            return SimpleNamespace(body=None, status="fetch_failed", url=url)
        return SimpleNamespace(body=body, status="ok", url=url)

    def fetch_bytes(self, url, cookie_header=""):
        self.fetch_bytes_called = True
        return SimpleNamespace(body=None, status="fetch_failed", url=url)


def test_auth_unset_returns_global_error(monkeypatch, tmp_path):
    _set_fake_expired_cookie(monkeypatch)
    _set_mocks(monkeypatch, OkPriceOnlyClient)
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "auth_unset"
    assert result["sections"] == {}


def test_ticker_invalid_returns_global_error(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    _set_mocks(monkeypatch, OkPriceOnlyClient)
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("abcd", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "ticker_invalid"
    assert result["sections"] == {}


def test_auth_expired_is_global_and_not_cached(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    saved = []
    _set_mocks(monkeypatch, AuthExpiredClient, cache_save=lambda ticker, data: saved.append(data))
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "auth_expired"
    assert result["sections"] == {}
    assert saved == []


def test_auth_expired_jp_global(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    saved = []
    _set_mocks(monkeypatch, AuthExpiredJPClient, cache_save=lambda ticker, data: saved.append(data))
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "auth_expired"
    assert result["sections"] == {}
    assert saved == []


def test_ticker_not_found_is_global_and_not_cached(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    saved = []
    _set_mocks(monkeypatch, TickerNotFoundClient, cache_save=lambda ticker, data: saved.append(data))
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("9999", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "ticker_not_found"
    assert saved == []


def test_ticker_not_found_jp_global(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    saved = []
    _set_mocks(monkeypatch, TickerNotFoundJPClient, cache_save=lambda ticker, data: saved.append(data))
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("9999", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "ticker_not_found"
    assert saved == []


def test_partial_success(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    _set_mocks(monkeypatch, PartialClient)
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["sections"]["price"]["status"] == "ok"
    assert "company_profile" in result["sections"]
    assert len(result["errors"]) > 0


class AuthExpiredOnAnalysisClient:
    """Direct tabs succeed, but analysis tab redirects to login (auth_expired)."""
    def fetch_html(self, url, cookie_header=""):
        if "Idtl70" in url:
            return SimpleNamespace(body=None, status="auth_expired", url="https://login.sbisec.co.jp/ETGate/")
        return SimpleNamespace(body="<table><tr><th>current</th><td>2150.5</td></tr></table>".encode(), status="ok", url=url)


class AuthExpiredOnPerformanceClient:
    """Price + analysis succeed, but performance popup redirects to login."""
    def fetch_html(self, url, cookie_header=""):
        if "report_summary" in url:
            return SimpleNamespace(body=None, status="auth_expired", url="https://login.sbisec.co.jp/ETGate/")
        if "Idtl70" in url:
            return SimpleNamespace(body="""<iframe src="https://graph.sbisec.co.jp/sbiscreener/analysis?token=synthetic&sym=3932.T"></iframe>
<a onclick="window.open('/ETGate/?sw_param1=report_summary&stock_sec_code_mul=3932','report_summary')">業績</a>""".encode(), status="ok", url=url)
        if "graph.sbisec.co.jp" in url:
            return SimpleNamespace(body="<table><tr><th>score</th><td>6.0</td><td>7.0</td><td>5.0</td></tr></table>".encode(), status="ok", url=url)
        return SimpleNamespace(body="<table><tr><th>current</th><td>2150.5</td></tr></table>".encode(), status="ok", url=url)


def test_auth_expired_on_analysis_is_global(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    saved = []
    _set_mocks(monkeypatch, AuthExpiredOnAnalysisClient, cache_save=lambda ticker, data: saved.append(data))
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "auth_expired"
    assert saved == []


def test_auth_expired_on_performance_is_global(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    saved = []
    _set_mocks(monkeypatch, AuthExpiredOnPerformanceClient, cache_save=lambda ticker, data: saved.append(data))
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "auth_expired"
    assert saved == []


class AuthExpiredHtmlOnPerformanceClient:
    """Performance popup returns 200 OK but body contains login page."""
    def fetch_html(self, url, cookie_header=""):
        if "report_summary" in url:
            return SimpleNamespace(body="<form action='/login'><input type='password'><input name='userid'></form>".encode(), status="ok", url=url)
        if "Idtl70" in url:
            return SimpleNamespace(body="""<iframe src="https://graph.sbisec.co.jp/sbiscreener/analysis?token=synthetic&sym=3932.T"></iframe>
<a onclick="window.open('/ETGate/?sw_param1=report_summary&stock_sec_code_mul=3932','report_summary')">業績</a>""".encode(), status="ok", url=url)
        if "graph.sbisec.co.jp" in url:
            return SimpleNamespace(body="<table><tr><th>score</th><td>6.0</td><td>7.0</td><td>5.0</td></tr></table>".encode(), status="ok", url=url)
        return SimpleNamespace(body="<table><tr><th>current</th><td>2150.5</td></tr></table>".encode(), status="ok", url=url)


def test_auth_expired_html_on_performance_is_global(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    saved = []
    _set_mocks(monkeypatch, AuthExpiredHtmlOnPerformanceClient, cache_save=lambda ticker, data: saved.append(data))
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["errors"][0]["code"] == "auth_expired"
    assert saved == []


class InfoNotAvailableClient:
    """Analysis tab has no iframe/popup links, but explicit per-section markers."""
    def fetch_html(self, url, cookie_header=""):
        if "Idtl70" in url:
            return SimpleNamespace(body="""スコア情報はありません
業績情報はありません
適時開示はありません""".encode(), status="ok", url=url)
        if "Idtl10" in url:
            return SimpleNamespace(body="<table><tr><th>current</th><td>2150.5</td></tr></table>".encode(), status="ok", url=url)
        if "Idtl20" in url:
            return SimpleNamespace(body="no news".encode(), status="ok", url=url)
        if "Idtl50" in url:
            return SimpleNamespace(body="no profile".encode(), status="ok", url=url)
        return SimpleNamespace(body=b"", status="ok", url=url)


def test_info_not_available_gives_not_available_status(monkeypatch, tmp_path):
    _set_fake_cookie(monkeypatch)
    _set_mocks(monkeypatch, InfoNotAvailableClient)
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    assert result["sections"]["company_scores"]["status"] == "not_available"
    assert result["sections"]["stock_reports"]["status"] == "not_available"
    assert result["sections"]["performance"]["status"] == "not_available"
    assert result["sections"]["disclosures"]["status"] == "not_available"


class MixedAvailableClient:
    """One widget has not-available marker, but iframe and popups are present."""
    def fetch_html(self, url, cookie_header=""):
        if "Idtl70" in url:
            return SimpleNamespace(body="""該当する情報はありません
<iframe src="https://graph.sbisec.co.jp/sbiscreener/analysis?token=synthetic&sym=3932.T"></iframe>
<a onclick="window.open('/ETGate/?sw_param1=report_summary&stock_sec_code_mul=3932','report_summary')">業績</a>
<a onclick="window.open('/ETGate/?sw_param1=report_disclose&stock_sec_code_mul=3932','report_disclose')">適時開示</a>""".encode(), status="ok", url=url)
        if "Idtl10" in url:
            return SimpleNamespace(body="<table><tr><th>current</th><td>2150.5</td></tr></table>".encode(), status="ok", url=url)
        if "Idtl20" in url:
            return SimpleNamespace(body="no news".encode(), status="ok", url=url)
        if "Idtl50" in url:
            return SimpleNamespace(body="no profile".encode(), status="ok", url=url)
        if "graph.sbisec.co.jp" in url:
            return SimpleNamespace(body="<table><tr><th>score</th><td>6.0</td><td>7.0</td><td>5.0</td></tr></table>".encode(), status="ok", url=url)
        if "report_summary" in url:
            return SimpleNamespace(body="<table></table>".encode(), status="ok", url=url)
        if "report_disclose" in url:
            return SimpleNamespace(body="<table></table>".encode(), status="ok", url=url)
        return SimpleNamespace(body=b"", status="ok", url=url)


def test_mixed_marker_and_valid_links_still_fetches(monkeypatch, tmp_path):
    """Global 'not available' text must not block sections with valid links."""
    _set_fake_cookie(monkeypatch)
    _set_mocks(monkeypatch, MixedAvailableClient)
    import fetch_stock_info as fsi
    result = fsi.fetch_stock_info("3932", cache_dir=tmp_path)
    # These sections have valid links and should be fetched (not blocked)
    assert result["sections"]["company_scores"]["status"] != "not_available"
    assert result["sections"]["performance"]["status"] != "not_available"
    assert result["sections"]["disclosures"]["status"] != "not_available"


def test_json_output_only_to_stdout(monkeypatch, tmp_path, capsys):
    _set_fake_cookie(monkeypatch)
    _set_mocks(monkeypatch, FullClient)
    import fetch_stock_info as fsi
    fsi.main(["3932", "--cache-dir", str(tmp_path)])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert_valid_stock_info(parsed)
    assert "ERROR" not in captured.out


def test_main_outputs_json_when_cookie_store_raises(monkeypatch, capsys):
    """When cookie_store throws, stdout must still be valid internal_error JSON."""
    fake = SimpleNamespace(
        read_cookie_bundle=lambda: (_ for _ in ()).throw(RuntimeError("broken"))
    )
    monkeypatch.setitem(sys.modules, "cookie_store", fake)
    from fetch_stock_info import main
    with pytest.raises(SystemExit) as exc:
        main(["3932", "--refresh"])
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"][0]["code"] == "internal_error"
    # Error message must not leak to stdout or contain internal details
    assert "RuntimeError" not in capsys.readouterr().out
    assert "broken" not in capsys.readouterr().out
