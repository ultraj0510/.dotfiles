"""Parse static IR index pages and crawl links within approved domain."""
import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_JAPANESE_DATE_PATTERNS = [
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
    re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})"),
]

_ARCHIVE_LABELS = re.compile(
    r"archive|library|past|過去|年度|\d{4}",
    re.IGNORECASE,
)

_JS_SHELL_MARKERS = re.compile(
    r'<div\s+id="(?:root|app|ir-)'
    r'|eir\.js|eir/'
    r'|data-sly-|clientlib',
)

def scan_index(start_url, window_start, window_end, approved_domain, http_client,
               max_depth=2, max_pages=20):
    """Crawl the IR index and return matching entries.

    Returns dict with keys: entries, visited_pages, complete, status, errors.
    """
    visited = set()
    errors = []
    entries = []
    to_visit = [(start_url, 0)]
    complete = True

    while to_visit:
        if len(visited) >= max_pages:
            complete = False
            break
        url, depth = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)

        result = http_client.fetch(url, {approved_domain}, 5 * 1024 * 1024)
        if result.status != "ok" or not result.body:
            errors.append({"url": url, "code": result.status, "message": "fetch failed"})
            complete = False
            continue

        html = _decode(result.body)
        if not html:
            errors.append({"url": url, "code": "decode_failed", "message": "Could not decode response"})
            complete = False
            continue

        page_entries, page_links = _parse_index_page(html, url, window_start, window_end, approved_domain)
        entries.extend(page_entries)

        if depth < max_depth:
            for link_url in page_links:
                if link_url not in visited:
                    if len(visited) + len(to_visit) < max_pages:
                        to_visit.append((link_url, depth + 1))
                    else:
                        complete = False

    status = "ok"
    if not entries and not errors and visited:
        for u in list(visited)[:1]:
            r = http_client.fetch(u, {approved_domain}, 5 * 1024 * 1024)
            if r.body:
                html = _decode(r.body)
                if html and _JS_SHELL_MARKERS.search(html):
                    status = "unsupported"
                    break
    if errors and not entries:
        status = "error"

    return {
        "entries": entries,
        "visited_pages": list(visited),
        "complete": complete,
        "status": status,
        "errors": errors,
    }


def _decode(body):
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


def _parse_index_page(html, base_url, window_start, window_end, approved_domain):
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    links = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href or href.startswith("javascript:") or href.startswith("#"):
            continue

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        host_domain = parsed.hostname or ""

        from safe_http import registrable_domain
        link_domain = registrable_domain(host_domain)

        # Archive links for further crawling
        if link_domain == approved_domain:
            text = a.get_text(" ", strip=True)
            href_lower = href.lower()
            if _ARCHIVE_LABELS.search(text) or _ARCHIVE_LABELS.search(href_lower):
                links.append(absolute)

        # Extract date from nearby text
        block = _nearest_block(a)
        date_str = _extract_date(block)

        if date_str:
            try:
                entry_date = date.fromisoformat(date_str)
                if window_start <= entry_date <= window_end:
                    entries.append({
                        "published_at": date_str,
                        "title": a.get_text(" ", strip=True)[:200],
                        "url": absolute,
                        "context": block[:500],
                    })
            except ValueError:
                pass

    return entries, links


def _nearest_block(element):
    for parent in element.parents:
        if parent.name == "td":
            row = parent.find_parent("tr")
            if row:
                return row.get_text(" ", strip=True)
            return parent.get_text(" ", strip=True)
        if parent.name in ("tr", "li", "article", "section", "div"):
            return parent.get_text(" ", strip=True)
        if parent.name == "body":
            break
    return element.get_text(" ", strip=True)


def _extract_date(text):
    for pattern in _JAPANESE_DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"
    return ""
