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
    r"archive|library|past|過去|年度|page=|p=\d+",
    re.IGNORECASE,
)

# Only match 4-digit years when in IR context (URL path contains ir/ or text has IR keyword)
_YEAR_IN_IR = re.compile(r"(?:ir/|ir$|ライブラリ|アーカイブ|過去|資料一覧|決算|報告)", re.IGNORECASE)

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
    scheduled = {start_url}
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
                if link_url not in visited and link_url not in scheduled:
                    if len(visited) + len(scheduled) < max_pages:
                        scheduled.add(link_url)
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

        text = a.get_text(" ", strip=True)
        href_lower = href.lower()

        # Archive/index links for further crawling (not documents)
        is_crawl_target = False
        if link_domain == approved_domain:
            if _ARCHIVE_LABELS.search(text) or _ARCHIVE_LABELS.search(href_lower):
                if _looks_like_crawl_target(href_lower):
                    links.append(absolute)
                    is_crawl_target = True
            elif re.search(r"\d{4}", text) or re.search(r"\d{4}", href_lower):
                # Year-only: require IR context to avoid crawling general news
                combined = f"{text} {absolute}"
                if _YEAR_IN_IR.search(combined) and _looks_like_crawl_target(href_lower):
                    links.append(absolute)
                    is_crawl_target = True

        # Skip crawl targets as document candidates
        if is_crawl_target:
            continue
        # Only treat as document candidate if link targets a file or document page
        if not _looks_like_document_target(href_lower, text):
            continue

        # Extract date from the nearest semantic block (not a page-wide container)
        block = _nearest_block(a)
        date_str = _extract_date(block)
        if not date_str:
            continue

        # Verify date is from the same row/card, not a distant heading
        if not _date_near_link(a, date_str):
            continue

        try:
            entry_date = date.fromisoformat(date_str)
            if window_start <= entry_date <= window_end:
                entries.append({
                    "published_at": date_str,
                    "title": text[:200],
                    "url": absolute,
                    "context": block[:500],
                })
        except ValueError:
            pass

    return entries, links


def _looks_like_crawl_target(href_lower):
    """Archive/year index pages, not document files."""
    return not _is_document_extension(href_lower)


def _looks_like_document_target(href_lower, text):
    """Link leads to a downloadable document or document detail page."""
    if _is_document_extension(href_lower):
        return True
    # .html pages only count if the link text contains document keywords
    if href_lower.endswith((".htm", ".html")):
        doc_keywords = ("決算", "報告", "説明", "短信", "発表", "計画", "予想",
                        "修正", "月次", "取得", "配当", "result", "report",
                        "presentation", "plan", "forecast", "material")
        return any(kw in text for kw in doc_keywords)
    return False


def _is_document_extension(href_lower):
    """Check URL path (not query/fragment) for document extensions."""
    from urllib.parse import urlparse
    path = urlparse(href_lower).path.lower()
    return any(path.endswith(ext) for ext in
               (".pdf", ".xlsx", ".xls", ".csv"))


def _date_near_link(link_element, date_str):
    """Check that the date is in the link's immediate container."""
    for depth, parent in enumerate(link_element.parents):
        if parent.name == "body":
            return False
        if parent.name in ("tr", "li", "article", "section"):
            # Re-extract date from container to verify semantic association
            parent_text = parent.get_text(" ", strip=True)
            if _extract_date(parent_text) == date_str:
                return True
            # Continue climbing if date not in this container
        if parent.name == "div" and depth <= 3:
            parent_text = parent.get_text(" ", strip=True)
            if _extract_date(parent_text) == date_str:
                return True
    return False


def _nearest_block(element):
    """Climb to a container that includes both date and link context.

    Walk up ancestors and select the first block-level element whose text
    contains at least two numeric tokens (typical for date + title) OR
    the first <tr>/<li>/<article>/<section> encountered.
    """
    for parent in element.parents:
        if parent.name == "td":
            row = parent.find_parent("tr")
            if row:
                return row.get_text(" ", strip=True)
            return parent.get_text(" ", strip=True)
        if parent.name in ("tr", "li", "article", "section"):
            return parent.get_text(" ", strip=True)
        if parent.name == "div":
            text = parent.get_text(" ", strip=True)
            digit_count = sum(1 for c in text if c.isdigit())
            # Climb past thin wrappers; stop at card/article-like containers
            classes = parent.get("class", [])
            class_str = " ".join(classes).lower() if classes else ""
            if digit_count >= 4 or any(
                kw in class_str for kw in ("card", "item", "entry", "block", "post", "article")
            ):
                return text
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
