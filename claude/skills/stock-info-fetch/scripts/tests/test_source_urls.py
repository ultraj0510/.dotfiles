from urllib.parse import parse_qs, urlparse

from fixtures import ANALYSIS_OUTER_HTML, SCORE_HTML_WITH_PDF
from source_urls import (
    build_detail_url,
    extract_analysis_sources,
    extract_stock_report_pdf_url,
)


def test_builds_observed_detail_urls():
    expected = {
        "price": ("WPLETsiR001Idtl10", "stockDetail", "0"),
        "news": ("WPLETsiR001Idtl20", "DefaultAID", "1"),
        "company_profile": ("WPLETsiR001Idtl50", "DefaultAID", "4"),
        "analysis": ("WPLETsiR001Idtl70", "DefaultAID", "6"),
    }
    for section, (page_id, action_id, output_type) in expected.items():
        url = build_detail_url("3932", section)
        query = parse_qs(urlparse(url).query)
        assert query["_PageID"] == [page_id], f"Wrong PageID for {section}: got {query['_PageID']}"
        assert query["_ActionID"] == [action_id], f"Wrong ActionID for {section}: got {query['_ActionID']}"
        assert query["i_output_type"] == [output_type], f"Wrong i_output_type for {section}: got {query['i_output_type']}"
        assert query["stock_sec_code_mul"] == ["3932"]


def test_analysis_section_url_has_correct_params():
    url = build_detail_url("7203", "analysis")
    query = parse_qs(urlparse(url).query)
    assert query["_PageID"] == ["WPLETsiR001Idtl70"]
    assert query["stock_sec_code_mul"] == ["7203"]
    assert query["_ControlID"] == ["WPLETsiR001Control"]


def test_extracts_observed_analysis_sources():
    result = extract_analysis_sources(
        ANALYSIS_OUTER_HTML,
        "https://site1.sbisec.co.jp/ETGate/",
    )
    assert result.score_url is not None
    assert urlparse(result.score_url).hostname == "graph.sbisec.co.jp"
    assert "report_summary" in result.performance_entry_url
    assert "report_disclose" in result.disclosures_entry_url


def test_extracts_pdf_from_score_iframe_not_outer_page():
    url = extract_stock_report_pdf_url(
        SCORE_HTML_WITH_PDF,
        "https://graph.sbisec.co.jp/sbiscreener/analysis",
    )
    assert url is not None
    assert urlparse(url).hostname == "app.stockreportsplus.com"


def test_extract_stock_report_pdf_url_returns_none_when_missing():
    url = extract_stock_report_pdf_url(
        "<div>no pdf link</div>",
        "https://graph.sbisec.co.jp/sbiscreener/analysis",
    )
    assert url is None


def test_build_detail_url_raises_for_unknown_section():
    try:
        build_detail_url("3932", "nonexistent")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass
