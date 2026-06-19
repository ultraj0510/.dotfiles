"""Remove sensitive authentication tokens from URLs for safe logging/output."""
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


SENSITIVE_PARAMS = {"token", "enc", "ahash", "hhash", "ihash"}


def clean_url(url: str) -> str:
    """Remove sensitive query parameters and fragment from a URL.

    Returns the URL with sensitive params stripped. The fragment is always
    removed since it never carries data we need to preserve.
    """
    parsed = urlparse(url)
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned = {k: v for k, v in params.items() if k not in SENSITIVE_PARAMS}
        query = urlencode(cleaned, doseq=True)
    else:
        query = ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path,
                       parsed.params, query, ""))
