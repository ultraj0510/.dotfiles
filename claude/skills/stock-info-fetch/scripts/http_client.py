"""Host-aware HTTP client that never sends SBI cookies to external hosts.

Host policy:
  - SBI cookies are only attached to site1.sbisec.co.jp and www.sbisec.co.jp
  - graph.sbisec.co.jp, sbi.ifis.co.jp, app.stockreportsplus.com never receive cookies
  - Cross-host redirects strip cookies
  - Unexpected redirect hosts produce "unexpected_host" status
"""
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from url_cleaner import clean_url

COOKIE_HOSTS = {"site1.sbisec.co.jp", "www.sbisec.co.jp"}
PUBLIC_HOSTS = {
    "graph.sbisec.co.jp",
    "sbi.ifis.co.jp",
    "app.stockreportsplus.com",
}
# Redirect targets that signal an expired session — no cookie sent, no body returned.
AUTH_REDIRECT_HOSTS = {"login.sbisec.co.jp"}
ALLOWED_HOSTS = COOKIE_HOSTS | PUBLIC_HOSTS
USER_AGENT = "Mozilla/5.0"


@dataclass(frozen=True)
class FetchResult:
    body: bytes | None
    status: str
    url: str
    content_type: str


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urlparse(newurl).hostname
        if host in AUTH_REDIRECT_HOSTS:
            raise URLError("auth_expired")
        if host not in ALLOWED_HOSTS:
            raise URLError("unexpected_host")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urlparse(req.full_url).hostname != host:
            redirected.remove_header("Cookie")
        return redirected


class SafeHttpClient:
    def __init__(self, transport=None):
        self.transport = transport or build_opener(SafeRedirectHandler())

    def _request(self, url: str, cookie_header: str) -> FetchResult:
        host = urlparse(url).hostname
        if host not in ALLOWED_HOSTS:
            return FetchResult(None, "unexpected_host", clean_url(url), "")
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja"}
        if cookie_header and host in COOKIE_HOSTS:
            headers["Cookie"] = cookie_header
        try:
            response = self.transport.open(Request(url, headers=headers), timeout=30)
            final_host = urlparse(response.geturl()).hostname
            if final_host in AUTH_REDIRECT_HOSTS:
                return FetchResult(None, "auth_expired", clean_url(response.geturl()), "")
            if final_host not in ALLOWED_HOSTS:
                return FetchResult(None, "unexpected_host", clean_url(response.geturl()), "")
            body = response.read()
            return FetchResult(
                body,
                "ok",
                clean_url(response.geturl()),
                response.headers.get_content_type(),
            )
        except URLError as exc:
            if "auth_expired" in str(exc):
                status = "auth_expired"
            elif "unexpected_host" in str(exc):
                status = "unexpected_host"
            else:
                status = "fetch_failed"
            return FetchResult(None, status, clean_url(url), "")
        except HTTPError:
            return FetchResult(None, "fetch_failed", clean_url(url), "")

    def fetch_html(self, url: str, cookie_header: str = "") -> FetchResult:
        return self._request(url, cookie_header)

    def fetch_bytes(self, url: str, cookie_header: str = "") -> FetchResult:
        return self._request(url, cookie_header)
