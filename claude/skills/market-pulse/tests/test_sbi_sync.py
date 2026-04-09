# tests/test_sbi_sync.py
import os
import pytest
from scripts.sbi_sync import parse_holdings_html, parse_account_html

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_parse_holdings_html_extracts_tickers():
    with open(os.path.join(FIXTURES, "sbi_holdings.html"), encoding="utf-8") as f:
        html = f.read()
    result = parse_holdings_html(html)
    tickers = [h["ticker"] for h in result]
    assert "7974" in tickers
    assert "9984" in tickers
    assert "285A" in tickers


def test_parse_holdings_html_extracts_quantity():
    with open(os.path.join(FIXTURES, "sbi_holdings.html"), encoding="utf-8") as f:
        html = f.read()
    result = parse_holdings_html(html)
    nintendo = next(h for h in result if h["ticker"] == "7974")
    assert nintendo["quantity"] == 100
    assert nintendo["name"] == "任天堂"


def test_parse_holdings_html_extracts_cost_price():
    with open(os.path.join(FIXTURES, "sbi_holdings.html"), encoding="utf-8") as f:
        html = f.read()
    result = parse_holdings_html(html)
    softbank = next(h for h in result if h["ticker"] == "9984")
    assert softbank["cost_price"] == 4200


def test_parse_holdings_html_empty_table_returns_empty():
    result = parse_holdings_html("<html><body><table></table></body></html>")
    assert result == []


def test_parse_account_html_extracts_totals():
    with open(os.path.join(FIXTURES, "sbi_account.html"), encoding="utf-8") as f:
        html = f.read()
    result = parse_account_html(html)
    assert result["total_assets"] == 9466965
    assert result["available_cash"] == 974965


def test_parse_account_html_empty_returns_none():
    result = parse_account_html("<html><body></body></html>")
    assert result["total_assets"] is None
    assert result["available_cash"] is None
