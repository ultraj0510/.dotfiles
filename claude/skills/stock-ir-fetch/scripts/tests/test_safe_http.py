import pytest

from safe_http import (
    FetchResult,
    SafeHttpClient,
    registrable_domain,
    resolve_addresses,
)


# --- registrable_domain ---

def test_registrable_domain_keeps_company_domain():
    assert registrable_domain("www.kioxia-holdings.com") == "kioxia-holdings.com"
    assert registrable_domain("www.example.co.jp") == "example.co.jp"


def test_registrable_domain_handles_bare_host():
    assert registrable_domain("localhost") == "localhost"


# --- URL scheme/userinfo rejection ---

def test_rejects_http(fake_transport):
    client = SafeHttpClient(transport=fake_transport)
    result = client.fetch("http://example.com/ir", {"example.com"}, 1024)
    assert result.status == "insecure_url"


def test_rejects_userinfo(fake_transport):
    client = SafeHttpClient(transport=fake_transport)
    result = client.fetch("https://user:pass@example.com/ir", {"example.com"}, 1024)
    assert result.status == "unsafe_url"


def test_rejects_unapproved_domain(fake_transport):
    client = SafeHttpClient(transport=fake_transport)
    result = client.fetch("https://other.com/ir", {"example.com"}, 1024)
    assert result.status == "unexpected_host"


# --- DNS / IP validation ---

def test_rejects_private_dns_resolution():
    def fake_resolver(host):
        return {"127.0.0.1"}

    client = SafeHttpClient(_resolver=fake_resolver)
    result = client.fetch("https://example.com/ir", {"example.com"}, 1024)
    assert result.status == "unsafe_address"


def test_rejects_link_local_address():
    def fake_resolver(host):
        return {"169.254.1.1"}

    client = SafeHttpClient(_resolver=fake_resolver)
    result = client.fetch("https://example.com/ir", {"example.com"}, 1024)
    assert result.status == "unsafe_address"


# --- Redirect handling ---

def test_rejects_redirect_to_unapproved_domain():
    class RedirectTransport:
        def __init__(self):
            self.calls = []

        def __call__(self, url):
            self.calls.append(url)
            return _FakeRedirectResponse("https://other.com/ir")

    client = SafeHttpClient(transport=RedirectTransport())
    result = client.fetch("https://example.com/ir", {"example.com"}, 1024)
    assert result.status == "unexpected_host"


def test_rejects_redirect_to_http():
    class RedirectTransport:
        def __init__(self):
            self.calls = []

        def __call__(self, url):
            self.calls.append(url)
            return _FakeRedirectResponse("http://example.com/ir")

    client = SafeHttpClient(transport=RedirectTransport())
    result = client.fetch("https://example.com/ir", {"example.com"}, 1024)
    assert result.status == "insecure_redirect"


# --- Size limit ---

def test_stops_at_size_limit():
    class LargeTransport:
        def __init__(self):
            self.calls = []

        def __call__(self, url):
            self.calls.append(url)
            return _FakeLargeResponse(b"x" * 1000)

    client = SafeHttpClient(transport=LargeTransport())
    result = client.fetch("https://example.com/ir", {"example.com"}, 5)
    assert result.status == "response_too_large"


# --- Successful fetch ---

def test_fetches_ok_with_valid_domain():
    class OkTransport:
        def __init__(self):
            self.calls = []

        def __call__(self, url):
            self.calls.append(url)
            return _FakeOkResponse(b"Hello IR", "text/html", url)

    client = SafeHttpClient(transport=OkTransport())
    result = client.fetch("https://example.com/ir", {"example.com"}, 1024)
    assert result.status == "ok"
    assert result.body == b"Hello IR"
    assert result.content_type == "text/html"


# --- Fake response helpers ---

class _FakeRedirectResponse:
    def __init__(self, location, code=302):
        self.code = code
        self.headers = {"Location": location}

    def read(self, size=-1):
        return b""


class _FakeLargeResponse:
    def __init__(self, body):
        self._body = body
        self._pos = 0

    def read(self, size=-1):
        if self._pos >= len(self._body):
            return b""
        chunk = self._body[self._pos:self._pos + max(size, 1)]
        self._pos += len(chunk)
        return chunk

    @property
    def code(self):
        return 200

    @property
    def headers(self):
        return {}

    @property
    def url(self):
        return "https://example.com/ir"


class _FakeOkResponse:
    def __init__(self, body, content_type, url):
        self._body = body
        self._pos = 0
        self._headers = {"Content-Type": content_type}
        self._url = url

    def read(self, size=-1):
        if self._pos >= len(self._body):
            return b""
        chunk = self._body[self._pos:self._pos + max(size, 1)]
        self._pos += len(chunk)
        return chunk

    @property
    def code(self):
        return 200

    @property
    def headers(self):
        return self._headers

    @property
    def url(self):
        return self._url


@pytest.fixture
def fake_transport():
    class FakeTransport:
        def __call__(self, url):
            return _FakeOkResponse(b"ok", "text/html", url)
    return FakeTransport()
