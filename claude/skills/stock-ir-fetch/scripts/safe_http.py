import ipaddress
import socket
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener

import tldextract


@dataclass(frozen=True)
class FetchResult:
    body: bytes | None
    status: str
    requested_url: str
    final_url: str
    content_type: str
    size: int


_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())


def registrable_domain(host):
    value = _EXTRACT((host or "").lower().rstrip("."))
    if not value.domain or not value.suffix:
        return host
    return f"{value.domain}.{value.suffix}"


def resolve_addresses(host):
    return {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}


MAX_REDIRECTS = 5
MAX_BODY_BYTES_DEFAULT = 50 * 1024 * 1024
CHUNK_SIZE = 65536
TIMEOUT_SECONDS = 30


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Block automatic redirect following so _handle_redirect validates every hop."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
    def http_error_301(self, req, fp, code, msg, headers):
        return fp
    def http_error_302(self, req, fp, code, msg, headers):
        return fp
    def http_error_303(self, req, fp, code, msg, headers):
        return fp
    def http_error_307(self, req, fp, code, msg, headers):
        return fp
    def http_error_308(self, req, fp, code, msg, headers):
        return fp


def _sanitize_content_type(value):
    if not value:
        return ""
    value = value.split(";")[0].strip().lower()
    return value


class SafeHttpClient:
    def __init__(self, transport=None, _resolver=None):
        self._transport = transport
        self._resolver = _resolver or resolve_addresses

    def fetch(self, url, allowed_domains, max_bytes=MAX_BODY_BYTES_DEFAULT):
        return self._fetch(url, allowed_domains, max_bytes, 0)

    def _fetch(self, url, allowed_domains, max_bytes, redirect_count):
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return FetchResult(None, "insecure_url", url, url, "", 0)
        if parsed.username or parsed.password:
            return FetchResult(None, "unsafe_url", url, url, "", 0)
        host = parsed.hostname or ""
        if registrable_domain(host) not in allowed_domains:
            return FetchResult(None, "unexpected_host", url, url, "", 0)
        if not _safe_host_via(host, self._resolver):
            return FetchResult(None, "unsafe_address", url, url, "", 0)

        resp = None
        if self._transport:
            try:
                resp = self._transport(url)
            except Exception as e:
                return FetchResult(None, "transport_error", url, url, "", 0)
        else:
            try:
                req = Request(url, method="GET")
                req.add_header("User-Agent", "stock-ir-fetch/1.0")
                req.add_header("Accept-Language", "ja,en;q=0.9")
                opener = build_opener(_NoRedirectHandler())
                resp = opener.open(req, timeout=TIMEOUT_SECONDS)
            except Exception as e:
                return FetchResult(None, "http_error", url, url, "", 0)

        return self._handle_redirect(resp, url, allowed_domains, max_bytes, redirect_count)

    def _handle_redirect(self, resp, url, allowed_domains, max_bytes, redirect_count):
        status_code = getattr(resp, 'code', 200)
        if status_code in (301, 302, 303, 307, 308):
            if redirect_count >= MAX_REDIRECTS:
                return FetchResult(None, "too_many_redirects", url, url, "", 0)
            location = resp.headers.get("Location") or resp.headers.get("location") or ""
            if not location:
                return FetchResult(None, "redirect_no_location", url, url, "", 0)
            next_url = urljoin(url, location)
            next_parsed = urlparse(next_url)
            if next_parsed.scheme != "https":
                return FetchResult(None, "insecure_redirect", url, next_url, "", 0)
            next_host = next_parsed.hostname or ""
            if registrable_domain(next_host) not in allowed_domains:
                return FetchResult(None, "unexpected_host", url, next_url, "", 0)
            if not _safe_host_via(next_host, self._resolver):
                return FetchResult(None, "unsafe_address", url, next_url, "", 0)
            return self._fetch(next_url, allowed_domains, max_bytes, redirect_count + 1)

        return self._read_response(resp, url, max_bytes)

    def _read_response(self, resp, url, max_bytes):
        content_type = _sanitize_content_type(
            resp.headers.get("Content-Type") or resp.headers.get("content-type", "")
        )
        final_url = getattr(resp, 'url', url) or url
        body = bytearray()
        while True:
            chunk = resp.read(CHUNK_SIZE)
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > max_bytes:
                return FetchResult(bytes(body), "response_too_large", url, final_url, content_type, len(body))
        return FetchResult(bytes(body), "ok", url, final_url, content_type, len(body))


def _safe_host_via(host, resolver):
    try:
        addresses = resolver(host)
    except OSError:
        return False
    if not addresses:
        return False
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            return False
    return True
