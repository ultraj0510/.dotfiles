"""Discover official IR source candidates from Yahoo Finance and company sites."""
import hashlib
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import yfinance as yf

from safe_http import registrable_domain
from ticker import to_yahoo_symbol


IR_LABELS = ("ir", "投資家", "株主", "investor")
INDEX_LABELS = (
    "irライブラ", "決算資料", "決算短信", "説明資料",
    "有価証券報告", "financial results", "library",
)


def candidate_id(company_url, ir_top_url, document_index_url):
    """Stable ID from normalized URLs (first 20 hex chars of SHA-256)."""
    normalized = "\n".join(
        _normalize_url(u) for u in (company_url, ir_top_url, document_index_url)
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:20]


def _normalize_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/') or '/'}" if parsed.scheme else url


class YahooCompanyMetadataProvider:
    """Minimal yfinance wrapper — company name and website only."""

    def lookup(self, ticker):
        symbol = to_yahoo_symbol(ticker)
        try:
            info = yf.Ticker(symbol).info
        except Exception:
            return {"company_name": "", "company_site_url": ""}
        name = info.get("longName") or info.get("shortName") or ""
        website = info.get("website") or ""
        if website and not website.startswith("https://"):
            website = ""
        return {"company_name": str(name), "company_site_url": str(website)}


def discover_ir_links(company_url, company_html, ir_top_html_or_url, ir_page_html):
    """Extract IR top URL and document index URL from static HTML.

    Returns dict with ir_top_url, document_index_url or None.
    """
    domain = registrable_domain(urlparse(company_url).hostname or "")

    def _same_domain(href):
        if not href or href.startswith("javascript:") or href.startswith("#"):
            return False
        absolute = urljoin(company_url, href)
        parsed = urlparse(absolute)
        return registrable_domain(parsed.hostname or "") == domain

    # Find IR top link from company page
    ir_top_url = ir_top_html_or_url if ir_top_html_or_url.startswith("https://") else ""
    if not ir_top_url and company_html:
        ir_top_url = _find_best_link(company_html, company_url, IR_LABELS, _same_domain)

    # Find document index from IR page
    document_index_url = ir_top_url or ""
    if ir_page_html and ir_top_url:
        found = _find_best_link(ir_page_html, ir_top_url, INDEX_LABELS, _same_domain)
        if found:
            document_index_url = found

    if ir_top_url:
        return {
            "ir_top_url": ir_top_url,
            "document_index_url": document_index_url,
        }
    return None


def _find_best_link(html, base_url, labels, domain_filter):
    soup = BeautifulSoup(html, "html.parser")
    best = None
    best_score = -1
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not domain_filter(href):
            continue
        absolute = urljoin(base_url, href)
        text = a.get_text(" ", strip=True).lower()
        href_lower = href.lower()
        score = 0
        for i, label in enumerate(labels):
            label_lower = label.lower()
            if label_lower in text:
                score += 3 - i * 0.5
            if label_lower in href_lower:
                score += 2
        if score > best_score:
            best_score = score
            best = absolute
    return best if best_score >= 2 else None


def discover_candidates(ticker, metadata_provider, http_client):
    """Return candidate dicts. Never writes files."""
    meta = metadata_provider.lookup(ticker)
    company_url = meta.get("company_site_url", "")
    company_name = meta.get("company_name", "")
    if not company_url or not company_url.startswith("https://"):
        return []
    domain = registrable_domain(urlparse(company_url).hostname or "")
    if not domain:
        return []
    candidates = []

    def add(ir_top, doc_index, evidence, warnings=None):
        cid = candidate_id(company_url, ir_top, doc_index)
        candidates.append({
            "candidate_id": cid,
            "ticker": ticker,
            "company_name": company_name,
            "company_site_url": company_url,
            "ir_top_url": ir_top,
            "document_index_url": doc_index,
            "approved_domain": domain,
            "evidence": evidence,
            "warnings": warnings or [],
        })

    company_html = _safe_fetch(http_client, company_url, domain)
    if not company_html:
        return []

    # Find IR link on company page
    ir_top = _find_best_link(company_html, company_url, IR_LABELS, lambda h: True)
    if ir_top:
        parsed = urlparse(ir_top)
        ir_domain = registrable_domain(parsed.hostname or "")
        if ir_domain != domain:
            # External IR page — not official
            return []
        ir_html = _safe_fetch(http_client, ir_top, domain)
        doc_index = ir_top
        if ir_html:
            found = _find_best_link(ir_html, ir_top, INDEX_LABELS, lambda h: True)
            if found:
                parsed2 = urlparse(found)
                if registrable_domain(parsed2.hostname or "") == domain:
                    doc_index = found
        # Verify company name on IR page
        evidence = ["ir_link_found"]
        if ir_html and (company_name[:4] in ir_html or ticker in ir_html):
            evidence.append("company_name_on_ir_page")
        add(ir_top, doc_index, evidence)

    return candidates


def _safe_fetch(http_client, url, domain):
    result = http_client.fetch(url, {domain}, 5 * 1024 * 1024)
    if result.status == "ok" and result.body:
        content_type = result.content_type
        if content_type in ("text/html", ""):
            for enc in ("utf-8", "cp932", "shift_jis"):
                try:
                    return result.body.decode(enc)
                except UnicodeDecodeError:
                    continue
    return ""


def validate_user_source(ticker, url, company_name, http_client):
    """Validate a user-provided IR URL. Returns source dict or None."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None
    domain = registrable_domain(parsed.hostname or "")
    if not domain:
        return None
    html = _safe_fetch(http_client, url, domain)
    if not html:
        return None
    # Check for company name evidence
    if company_name and company_name[:4] not in html and ticker not in html:
        return None
    now_iso = __import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("Asia/Tokyo")).isoformat()
    return {
        "schema_version": "1.0",
        "ticker": ticker,
        "company_name": company_name,
        "company_site_url": url,
        "ir_top_url": url,
        "document_index_url": url,
        "approved_domain": domain,
        "approved_at": now_iso,
        "approval_method": "user",
        "last_verified_at": now_iso,
        "last_successful_sync_at": None,
    }
