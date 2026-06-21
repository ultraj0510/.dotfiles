"""Fetch and validate IR documents by signature and content type."""
import hashlib
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

MEDIA_TYPES = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "text/csv": "csv",
}

SENSITIVE_PARAMS = {"token", "session", "auth", "signature", "x-amz-signature"}
LOGIN_MARKERS = (b"<input type=password", b'<input type="password"', b"name=password",
                 b"403 Forbidden", b"<title>Login", b"<title>Sign in")


def _clean_url(url):
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if k.lower() not in SENSITIVE_PARAMS}
    new_query = urlencode(cleaned, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _sha256(body):
    return hashlib.sha256(body).hexdigest()


def fetch_document(url, approved_domains, delivery_domains, http_client):
    """Fetch and validate a document. Returns (FetchedDocument | None, error_dict | None)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    from safe_http import registrable_domain
    domain = registrable_domain(host)
    if domain not in approved_domains and domain not in delivery_domains:
        return None, {"code": "unexpected_host", "message": f"Domain {domain} not approved"}

    allowed = approved_domains | delivery_domains
    result = http_client.fetch(url, allowed, 50 * 1024 * 1024)
    if result.status != "ok" or not result.body:
        return None, {"code": result.status, "message": f"Fetch failed: {result.status}"}

    body = result.body
    content_type = result.content_type

    # Determine extension
    extension = MEDIA_TYPES.get(content_type, "")
    if not extension:
        # Try to detect from signature
        detected = _detect_signature(body)
        if detected:
            extension = detected
        else:
            return None, {"code": "unknown_media_type", "message": f"Cannot handle {content_type}"}

    # Validate format
    sig_error = _validate_signature(body, extension)
    if sig_error:
        return None, sig_error

    # Reject login/error HTML when PDF expected
    if extension in ("pdf", "xlsx", "xls", "csv"):
        if any(marker in body[:2000] for marker in LOGIN_MARKERS):
            return None, {"code": "login_page_returned", "message": "Response appears to be a login page"}

    doc = {
        "body": body,
        "final_url": _clean_url(result.final_url),
        "media_type": content_type,
        "extension": extension,
        "sha256": _sha256(body),
        "size": len(body),
    }
    return doc, None


def _detect_signature(body):
    if body.startswith(b"%PDF"):
        return "pdf"
    if body.startswith(b"PK\x03\x04"):
        return "xlsx"
    if body.startswith(b"<!doctype html") or body.startswith(b"<html") or body.startswith(b"<!DOCTYPE HTML"):
        return "html"
    return ""


def _validate_signature(body, extension):
    if extension == "pdf" and not body.startswith(b"%PDF"):
        return {"code": "document_signature_mismatch", "message": "Expected PDF signature"}
    if extension in ("xlsx", "xls") and not body.startswith(b"PK\x03\x04"):
        return {"code": "document_signature_mismatch", "message": "Expected ZIP/XLSX signature"}
    return None
