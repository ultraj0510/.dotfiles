from prompt_context import build_prompt_context

MOCK_EVIDENCE_PACK = {
    "ticker": "285A",
    "company_name": "キオクシアHD",
    "evidence": [
        {"evidence_id": "price-2026-06-26-close", "kind": "market_data",
         "field": "close", "value": 92180.0, "unit": "JPY", "source_type": "stock-price-fetch",
         "source_ref": "daily:2026-06-26", "usable": True, "period_end": "2026-06-26"},
        {"evidence_id": "info-profile-sector", "kind": "fundamentals",
         "field": "sector", "value": "電気機器", "unit": None, "source_type": "stock-info-fetch",
         "source_ref": "company_profile:sector", "usable": True},
        {"evidence_id": "info-perf-revenue", "kind": "fundamentals",
         "field": "revenue", "value": "2,500,000百万円", "unit": None, "source_type": "stock-info-fetch",
         "source_ref": "performance:revenue", "usable": True},
        {"evidence_id": "info-score-overall", "kind": "fundamentals",
         "field": "overall_score", "value": 5, "unit": None, "source_type": "stock-info-fetch",
         "source_ref": "scores:overall", "usable": True},
        {"evidence_id": "ir-abc123", "kind": "ir_document",
         "field": "securities_report", "value": "有価証券報告書",
         "unit": None, "source_type": "stock-ir-fetch",
         "source_ref": "ir:abc123", "usable": True, "published_at": "2026-06-24"},
    ],
    "data_quality": {"price_freshness_hours": 24, "ir_coverage": "partial"},
}

MOCK_MARKET_METRICS = {
    "returns": {"total_return_pct": 5657.65, "return_20d_pct": 27.14},
    "moving_averages": {"sma_25": 82035.6, "sma_75": 48658.73, "price_vs_sma25_pct": 12.37, "price_vs_sma75_pct": 89.44},
    "rsi": {"latest": 57.8},
    "macd": {"macd_line": 11085.04, "signal": 11628.07, "histogram": -543.04},
    "bollinger": {"upper": 110840.24, "middle": 86765.0, "lower": 62689.76, "position_pct": 61.2},
    "volatility": {"daily_sigma": 0.06065, "annual_sigma_pct": 96.28, "max_drawdown_pct": 52.11},
    "volume": {"latest": 43906600, "avg_20d": 37856305, "ratio_vs_avg": 1.16},
}


def test_build_prompt_context_has_all_sections():
    ctx = build_prompt_context(MOCK_EVIDENCE_PACK, MOCK_MARKET_METRICS)
    for key in ("company_profile", "performance", "company_scores", "current_price",
                 "latest_market", "ir_documents", "data_quality", "evidence_counts"):
        assert key in ctx, f"Missing key: {key}"


def test_current_price_from_market_data():
    ctx = build_prompt_context(MOCK_EVIDENCE_PACK, MOCK_MARKET_METRICS)
    assert ctx["current_price"] == 92180.0


def test_company_profile_from_fundamentals():
    ctx = build_prompt_context(MOCK_EVIDENCE_PACK, MOCK_MARKET_METRICS)
    assert ctx["company_profile"]["sector"] == "電気機器"


def test_performance_from_fundamentals():
    ctx = build_prompt_context(MOCK_EVIDENCE_PACK, MOCK_MARKET_METRICS)
    assert len(ctx["performance"]) >= 1
    assert any(e["value"] == "2,500,000百万円" for e in ctx["performance"])


def test_company_scores_from_fundamentals():
    ctx = build_prompt_context(MOCK_EVIDENCE_PACK, MOCK_MARKET_METRICS)
    assert ctx["company_scores"]["overall_score"] == 5


def test_ir_documents_extracted():
    ctx = build_prompt_context(MOCK_EVIDENCE_PACK, MOCK_MARKET_METRICS)
    assert len(ctx["ir_documents"]) >= 1
    assert ctx["ir_documents"][0]["title"] == "有価証券報告書"


def test_latest_market_includes_key_indicators():
    ctx = build_prompt_context(MOCK_EVIDENCE_PACK, MOCK_MARKET_METRICS)
    m = ctx["latest_market"]
    assert m["rsi"] == 57.8
    assert m["sma_25"] == 82035.6
    assert m["bollinger_position_pct"] == 61.2
    assert m["volatility_annual_pct"] == 96.28


def test_evidence_counts():
    ctx = build_prompt_context(MOCK_EVIDENCE_PACK, MOCK_MARKET_METRICS)
    assert ctx["evidence_counts"]["market_data"] >= 1
    assert ctx["evidence_counts"]["fundamentals"] >= 2
    assert ctx["evidence_counts"]["ir_document"] >= 1


def test_ir_documents_none_dates_sort_last():
    pack = {
        "evidence": [
            {"evidence_id": "ir-1", "kind": "ir_document", "field": "r1", "value": "Doc A",
             "source_type": "ir", "source_ref": "ir:1", "usable": True, "published_at": "2026-06-24"},
            {"evidence_id": "ir-2", "kind": "ir_document", "field": "r2", "value": "Doc B",
             "source_type": "ir", "source_ref": "ir:2", "usable": True},  # No published_at
            {"evidence_id": "ir-3", "kind": "ir_document", "field": "r3", "value": "Doc C",
             "source_type": "ir", "source_ref": "ir:3", "usable": True, "published_at": "2026-06-25"},
        ],
    }
    ctx = build_prompt_context(pack, {})
    docs = ctx["ir_documents"]
    assert len(docs) == 3
    # Latest date first (descending by date, None at end)
    assert docs[0]["title"] == "Doc C"  # 2026-06-25
    assert docs[1]["title"] == "Doc A"  # 2026-06-24
    assert docs[2]["title"] == "Doc B"  # None


def test_empty_evidence_pack_returns_minimal_context():
    ctx = build_prompt_context({"evidence": []}, {})
    assert ctx["current_price"] is None
    assert ctx["company_profile"] == {}
    assert ctx["ir_documents"] == []
    assert ctx["evidence_counts"] == {}
