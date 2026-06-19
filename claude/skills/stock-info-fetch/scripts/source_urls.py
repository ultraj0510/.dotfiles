"""Real-page-confirmed SBI stock detail URL builder and analysis source extractors.

URL patterns confirmed 2026-06-19. Do not substitute estimated values.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

BASE_URL = "https://site1.sbisec.co.jp/ETGate/"
DETAIL_PAGES = {
    "price": ("WPLETsiR001Idtl10", "stockDetail", "0"),
    "news": ("WPLETsiR001Idtl20", "DefaultAID", "1"),
    "company_profile": ("WPLETsiR001Idtl50", "DefaultAID", "4"),
    "analysis": ("WPLETsiR001Idtl70", "DefaultAID", "6"),
}


@dataclass(frozen=True)
class AnalysisSources:
    score_url: str | None
    performance_entry_url: str | None
    disclosures_entry_url: str | None


def build_detail_url(ticker: str, section: str) -> str:
    page_id, action_id, output_type = DETAIL_PAGES[section]
    query = {
        "_ControlID": "WPLETsiR001Control",
        "_PageID": page_id,
        "_DataStoreID": "DSWPLETsiR001Control",
        "_ActionID": action_id,
        "i_dom_flg": "1",
        "i_output_type": output_type,
        "exchange_code": "TKY",
        "stock_sec_code_mul": ticker,
        "ref_from": "1",
        "ref_to": "20",
    }
    return f"{BASE_URL}?{urlencode(query)}"


def _popup_url(anchor, base_url: str) -> str | None:
    onclick = anchor.get("onclick", "")
    match = re.search(r"window\.open\('([^']+)'", onclick)
    return urljoin(base_url, match.group(1)) if match else None


def extract_analysis_sources(html: str, base_url: str) -> AnalysisSources:
    soup = BeautifulSoup(html, "html.parser")
    iframe = soup.find("iframe", src=lambda value: value and "/sbiscreener/analysis" in value)
    performance = soup.find("a", string=lambda value: value and value.strip() == "業績")
    disclosures = soup.find("a", string=lambda value: value and value.strip() == "適時開示")
    return AnalysisSources(
        score_url=urljoin(base_url, iframe["src"]) if iframe else None,
        performance_entry_url=_popup_url(performance, base_url) if performance else None,
        disclosures_entry_url=_popup_url(disclosures, base_url) if disclosures else None,
    )


def extract_stock_report_pdf_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find(
        "a",
        href=lambda value: value
        and "app.stockreportsplus.com/" in value
        and ".pdf" in value.lower(),
    )
    return urljoin(base_url, link["href"]) if link else None
