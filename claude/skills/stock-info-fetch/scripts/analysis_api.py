"""Fetch and parse the graph.sbisec.co.jp analysis JSON API.

The analysis tab on SBI contains an iframe pointing to a React SPA.
The SPA loads its data from a JSON endpoint:
  /sbiscrapi/data/analysisinfo?ric=<TICKER>.T&token=<TOKEN>

This module extracts the token and RIC from the iframe URL, fetches
the JSON API without SBI cookies, and returns structured facts.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from url_cleaner import clean_url

# API key → display label mapping, confirmed against SBI UI.
# Labels: 総合, 財務健全性, 収益性, 割安性, 安定性, 株価モメンタム
SCORE_KEY_MAP = {
    "avg_score": "total_score",
    "fund_score": "financial_health",
    "analyst_score": "profitability",
    "rc_score": "valuation",
    "risk_score": "stability",
    "tech_score": "price_momentum",
}


@dataclass
class AnalysisApiResult:
    scores: dict[str, float] = field(default_factory=dict)
    target_price: float | None = None
    target_last_update: str | None = None
    srplus_pdf_url: str | None = None
    status: str = "ok"
    error_message: str = ""


def build_analysis_api_url(iframe_src: str) -> str | None:
    """Extract token and RIC from the score iframe src, return the JSON API URL.

    Input: https://graph.sbisec.co.jp/sbiscreener/analysis?token=XXX&sym=285A.T
    Output: https://graph.sbisec.co.jp/sbiscrapi/data/analysisinfo?ric=285A.T&token=XXX
    """
    parsed = urlparse(iframe_src)
    if parsed.hostname not in ("graph.sbisec.co.jp",):
        return None
    params = parse_qs(parsed.query)
    token = params.get("token", [None])[0]
    sym = params.get("sym", [None])[0]
    if not token or not sym:
        return None
    # Validate RIC format: digits+optional letter followed by .T
    if not re.match(r"^\d{3,4}[A-Z]?\.T$", sym):
        return None
    # Validate token: hex string only
    if not re.match(r"^[0-9A-Fa-f]+$", token):
        return None
    safe_ric = sym
    safe_token = token
    return f"https://graph.sbisec.co.jp/sbiscrapi/data/analysisinfo?ric={safe_ric}&token={safe_token}"


def parse_analysis_api_response(body: bytes) -> AnalysisApiResult:
    """Parse the JSON API response into structured facts.

    No SBI cookie is sent with this request (graph.sbisec.co.jp is public).
    The API URL containing the ephemeral token is never returned to the caller.
    """
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return AnalysisApiResult(status="error", error_message=str(e)[:200])

    result = AnalysisApiResult()

    # Scores: pick the CO_SCORE entry (company scores, not industry average)
    scores_list = data.get("score", [])
    co_score = None
    for s in scores_list:
        if isinstance(s, dict) and s.get("type") == "CO_SCORE":
            co_score = s
            break
    if co_score:
        mapped = {}
        extracted = 0
        for api_key, label in SCORE_KEY_MAP.items():
            val = co_score.get(api_key)
            if val is not None:
                try:
                    fval = float(val)
                    if 1.0 <= fval <= 10.0:
                        mapped[label] = fval
                        extracted += 1
                except (ValueError, TypeError):
                    pass
        if extracted == 6:
            result.scores = mapped
        elif extracted > 0:
            result.scores = mapped  # partial — orchestrator decides
            result.status = "source_changed"

    # Target price
    tp = data.get("targetprice", {})
    if isinstance(tp, dict):
        curr = tp.get("curr_price")
        if curr is not None:
            try:
                result.target_price = float(curr)
            except (ValueError, TypeError):
                pass
        lu = tp.get("last_update")
        if lu is not None:
            try:
                from datetime import datetime, timezone
                ms = int(lu)
                dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
                result.target_last_update = dt.isoformat()
            except (ValueError, TypeError, OSError):
                pass

    # STOCK REPORTS PDF link
    asset = data.get("asset", {})
    if isinstance(asset, dict):
        pdf = asset.get("srplus_link", "")
        if pdf and isinstance(pdf, str) and pdf.startswith("https://app.stockreportsplus.com/"):
            result.srplus_pdf_url = pdf  # raw URL with enc — clean_url only on output

    return result


def extract_score_iframe_token_params(iframe_src: str) -> dict[str, str]:
    """Parse the iframe URL into its RIC and token components.
    Used for provenance only — token is never returned in output.
    """
    parsed = urlparse(iframe_src)
    params = parse_qs(parsed.query)
    return {
        "ric": (params.get("sym", [""])[0]),
        "source_host": parsed.netloc,
    }
