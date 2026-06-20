"""Tests for the analysis JSON API parser."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis_api import (
    AnalysisApiResult,
    build_analysis_api_url,
    parse_analysis_api_response,
    SCORE_KEY_MAP,
)

# Sanitized fixture: API response structure without real token values.
_API_FIXTURE = {
    "score": [
        {
            "analyst_score": "5.0",
            "avg_score": "6.0",
            "fund_score": "7.0",
            "rc_score": "8.0",
            "risk_score": "3.0",
            "tech_score": "9.0",
            "type": "CO_SCORE",
        },
        {
            "avg_score": "4.2",
            "type": "IND_SCORE",
        },
    ],
    "asset": {
        "stockName": "テスト",
        "srplus_link": "https://app.stockreportsplus.com/StockReportsLabCi_ja_JP/R611_285A-TO_ja_JP.pdf?enc=synthetic",
    },
    "targetprice": {
        "curr_price": "108600.0",
        "last_update": 1781692172000,
        "high": "200000.0",
        "low": "7000.0",
    },
}


def test_builds_api_url_from_iframe_src():
    src = "https://graph.sbisec.co.jp/sbiscreener/analysis?token=2B19EE5219A54B9D9FC1FBFFB8CFF2AB&sym=285A.T"
    url = build_analysis_api_url(src)
    assert url is not None
    assert "/sbiscrapi/data/analysisinfo" in url
    assert "ric=285A.T" in url
    assert "token=2B19EE5219A54B9D9FC1FBFFB8CFF2AB" in url


def test_builds_api_url_returns_none_without_token():
    assert build_analysis_api_url("https://graph.sbisec.co.jp/sbiscreener/analysis?sym=285A.T") is None


def test_parses_scores_from_api_response():
    body = json.dumps(_API_FIXTURE).encode()
    result = parse_analysis_api_response(body)
    assert result.status == "ok"
    assert result.scores["total_score"] == 6.0
    assert result.scores["financial_health"] == 7.0
    assert result.scores["profitability"] == 5.0
    assert result.scores["valuation"] == 8.0
    assert result.scores["stability"] == 3.0
    assert result.scores["price_momentum"] == 9.0


def test_parses_target_price():
    body = json.dumps(_API_FIXTURE).encode()
    result = parse_analysis_api_response(body)
    assert result.target_price == 108600.0
    assert result.target_last_update is not None


def test_parses_srplus_pdf_link():
    body = json.dumps(_API_FIXTURE).encode()
    result = parse_analysis_api_response(body)
    assert result.srplus_pdf_url is not None
    assert "app.stockreportsplus.com" in result.srplus_pdf_url
    # Raw URL preserved for transport; clean_url applied at output


def test_handles_invalid_json():
    result = parse_analysis_api_response(b"not json")
    assert result.status == "error"


def test_handles_empty_response():
    result = parse_analysis_api_response(b"{}")
    assert result.status == "ok"
    assert result.scores == {}


def test_score_mapping_has_six_dimensions():
    assert len(SCORE_KEY_MAP) == 6
    assert set(SCORE_KEY_MAP.values()) == {
        "total_score", "financial_health", "profitability",
        "valuation", "stability", "price_momentum",
    }
