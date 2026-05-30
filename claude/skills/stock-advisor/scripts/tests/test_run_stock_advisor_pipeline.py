"""Tests for run_stock_advisor_pipeline.py helpers."""

import pathlib

from run_stock_advisor_pipeline import collect_tickers


def test_collect_tickers_combines_holdings_and_watchlist(tmp_path):
    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\n  - ticker: 1515.T\n  - ticker: 285A.T\n  - ticker: 1515.T\n")
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("- ticker: 7203.T\n- ticker: 285A.T\n")
    assert collect_tickers(portfolio, watchlist) == ["1515.T", "285A.T", "7203.T"]


def test_collect_tickers_works_without_watchlist(tmp_path):
    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\n  - ticker: 5803.T\n")
    watchlist = tmp_path / "missing.yaml"
    assert collect_tickers(portfolio, watchlist) == ["5803.T"]
