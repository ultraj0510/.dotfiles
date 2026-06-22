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

_IR_NAV_LABELS = re.compile(
    r"IRニュース|IRライブラ|決算短信|決算説明|有価証券|半期報告|"
    r"統合報告|IRイベント|経営方針|Investor|archive|library|past|過去|"
    r"page=|p=\d+",
    re.IGNORECASE,
)

def scan_index(start_urls, window_start, window_end, approved_domain, http_client,
               ir_root_paths=(), max_depth=2, max_pages=24):
    """Crawl the IR index and return matching entries.

    Returns dict with keys: entries, visited_pages, complete, status, errors, dynamic_pages.
    """
    if isinstance(start_urls, str):
        start_urls = [start_urls]
    ordered_starts = list(dict.fromkeys(start_urls))
    scheduled = set(ordered_starts)
    to_visit = [(url, 0) for url in ordered_starts]
    visited = set()
    errors = []
    entries = []
    dynamic_pages = []
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

        page_entries, page_links = _parse_index_page(html, url, window_start, window_end, approved_domain, ir_root_paths)
        entries.extend(page_entries)

        if depth < max_depth:
            for link_url in page_links:
                if link_url not in scheduled:
                    if len(scheduled) < max_pages:
                        scheduled.add(link_url)
                        to_visit.append((link_url, depth + 1))
                    else:
                        complete = False

    status = "ok"
    # Only mark unsupported for single-page visits with JS markers
    if not entries and not errors and len(visited) == 1:
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
        "dynamic_pages": dynamic_pages,
    }


def _decode(body):
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


def _parse_index_page(html, base_url, window_start, window_end, approved_domain, ir_root_paths=()):
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
            if ir_root_paths:
                if _is_ir_navigation_target(absolute, text, approved_domain, ir_root_paths):
                    links.append(absolute)
                    is_crawl_target = True
            elif _ARCHIVE_LABELS.search(text) or _ARCHIVE_LABELS.search(href_lower):
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

        context = _entry_context(a)
        if context is None:
            continue
        block, date_str = context

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


def _is_ir_navigation_target(absolute_url, text, approved_domain, ir_root_paths):
    from safe_http import registrable_domain
    parsed = urlparse(absolute_url)
    if registrable_domain(parsed.hostname or "") != approved_domain:
        return False
    if _is_document_extension(absolute_url.lower()):
        return False
    path = parsed.path.rstrip("/")
    if not any(path == root or path.startswith(f"{root}/") or path.startswith(f"{root}.")
               for root in ir_root_paths):
        return False
    return bool(_IR_NAV_LABELS.search(f"{text} {absolute_url}"))


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


def _extract_dates(text):
    dates = []
    for pattern in _JAPANESE_DATE_PATTERNS:
        for match in pattern.finditer(text):
            year, month, day = map(int, match.groups())
            try:
                parsed = date(year, month, day)
            except ValueError:
                continue
            if 2000 <= parsed.year <= 2030:
                value = parsed.isoformat()
                if value not in dates:
                    dates.append(value)
    return dates


def _entry_context(link_element):
    for depth, parent in enumerate(link_element.parents):
        if parent.name == "body" or depth > 8:
            break
        text = parent.get_text(" ", strip=True)
        if not text or len(text) > 1200:
            continue
        dates = _extract_dates(text)
        if len(dates) != 1:
            continue
        if parent.name in ("tr", "li", "article"):
            return text, dates[0]
        if parent.name == "div":
            classes = " ".join(parent.get("class", [])).lower()
            if depth <= 4 or any(
                token in classes
                for token in ("card", "item", "entry", "box", "row", "grid", "container")
            ):
                return text, dates[0]
    return None


def _extract_date(text):
    for pattern in _JAPANESE_DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"
    return ""
