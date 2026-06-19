"""Tests for SafeHttpClient — host-based cookie policy and redirect safety."""
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from http_client import SafeHttpClient, COOKIE_HOSTS, PUBLIC_HOSTS, ALLOWED_HOSTS


class FakeTransport:
    """Records requests and returns a fixed response."""
    def __init__(self, body=b"<html>ok</html>", final_url="https://site1.sbisec.co.jp/ETGate/",
                 content_type="text/html"):
        self.requests = []
        self._body = body
        self._final_url = final_url
        self._content_type = content_type

    def open(self, req, timeout=30):
        self.requests.append(req)
        resp = SimpleNamespace()
        resp.read = lambda: self._body
        resp.geturl = lambda: self._final_url
        resp.headers = SimpleNamespace(get_content_type=lambda: self._content_type)
        return resp


class FakeRedirectTransport:
    """Simulates a redirect: first request to SBI, second to sbi.ifis.co.jp."""
    def __init__(self):
        self.requests = []
        self._call = 0

    def open(self, req, timeout=30):
        self.requests.append(req)
        self._call += 1
        resp = SimpleNamespace()
        if self._call == 1:
            resp.read = lambda: b"<html>redirecting...</html>"
            resp.geturl = lambda: "https://sbi.ifis.co.jp/index.php?Param1=report_summary"
        else:
            resp.read = lambda: b"<html>performance data</html>"
            resp.geturl = lambda: "https://sbi.ifis.co.jp/index.php?Param1=report_summary"
        resp.headers = SimpleNamespace(get_content_type=lambda: "text/html")
        return resp


class FakeUnexpectedRedirectTransport:
    """Redirects to an unexpected host (phishing.test)."""
    def open(self, req, timeout=30):
        resp = SimpleNamespace()
        resp.read = lambda: b"<html>phish</html>"
        resp.geturl = lambda: "https://phishing.test/steal"
        resp.headers = SimpleNamespace(get_content_type=lambda: "text/html")
        return resp


def test_cookie_is_only_attached_to_sbi_entry_request():
    transport = FakeTransport()
    client = SafeHttpClient(transport=transport)
    client.fetch_html(
        "https://site1.sbisec.co.jp/ETGate/?entry=1",
        cookie_header="session_a=value_a",
    )
    assert len(transport.requests) >= 1
    assert transport.requests[0].get_header("Cookie") == "session_a=value_a"


def test_public_hosts_never_receive_cookie():
    for url in (
        "https://graph.sbisec.co.jp/sbiscreener/analysis?token=synthetic",
        "https://sbi.ifis.co.jp/index.php?Param1=report_summary",
        "https://app.stockreportsplus.com/report.pdf?enc=synthetic",
    ):
        transport = FakeTransport(final_url=url)
        client = SafeHttpClient(transport=transport)
        client.fetch_html(url, cookie_header="session_a=value_a")
        assert len(transport.requests) >= 1
        assert transport.requests[-1].get_header("Cookie") is None, f"Cookie leaked to {url}"


def test_rejects_unexpected_redirect_host():
    result = SafeHttpClient(transport=FakeUnexpectedRedirectTransport()).fetch_html(
        "https://site1.sbisec.co.jp/ETGate/?entry=1",
        cookie_header="session_a=value_a",
    )
    assert result.status == "unexpected_host"


def test_unexpected_host_without_cookie_is_rejected():
    result = SafeHttpClient(transport=FakeUnexpectedRedirectTransport()).fetch_html(
        "https://graph.sbisec.co.jp/analysis",
    )
    assert result.status == "unexpected_host"


def test_fetch_bytes_returns_body():
    transport = FakeTransport(body=b"%PDF-1.4 fake pdf", content_type="application/pdf",
                              final_url="https://app.stockreportsplus.com/report.pdf")
    client = SafeHttpClient(transport=transport)
    result = client.fetch_bytes("https://app.stockreportsplus.com/report.pdf")
    assert result.status == "ok"
    assert result.body == b"%PDF-1.4 fake pdf"


class FakeLoginRedirectTransport:
    """Simulates a redirect to login.sbisec.co.jp (auth expired)."""
    def open(self, req, timeout=30):
        resp = SimpleNamespace()
        resp.read = lambda: b"<html>login</html>"
        resp.geturl = lambda: "https://login.sbisec.co.jp/ETGate/"
        resp.headers = SimpleNamespace(get_content_type=lambda: "text/html")
        return resp


def test_login_redirect_returns_auth_expired():
    result = SafeHttpClient(transport=FakeLoginRedirectTransport()).fetch_html(
        "https://site1.sbisec.co.jp/ETGate/?entry=1",
        cookie_header="session_a=value_a",
    )
    assert result.status == "auth_expired"


def test_fetch_html_decodes_body():
    transport = FakeTransport(body="<html>テスト</html>".encode("utf-8"))
    client = SafeHttpClient(transport=transport)
    result = client.fetch_html("https://site1.sbisec.co.jp/ETGate/")
    assert result.status == "ok"
    assert result.body == "<html>テスト</html>".encode("utf-8")
