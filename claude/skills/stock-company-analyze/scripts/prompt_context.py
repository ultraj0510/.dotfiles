def build_prompt_context(evidence_pack: dict, market_metrics: dict) -> dict:
    evidence = evidence_pack.get("evidence", [])

    company_profile = {}
    performance = []
    company_scores = {}
    ir_documents = []
    evidence_counts = {}

    for item in evidence:
        kind = item.get("kind")
        source_ref = item.get("source_ref", "")

        # Count by kind
        evidence_counts[kind] = evidence_counts.get(kind, 0) + 1

        if kind == "fundamentals":
            if source_ref.startswith("company_profile:"):
                company_profile[item["field"]] = item["value"]
            elif source_ref.startswith("performance:"):
                performance.append({"field": item["field"], "value": item["value"]})
            elif source_ref.startswith("scores:"):
                company_scores[item["field"]] = item["value"]

        elif kind == "ir_document" and item.get("usable"):
            ir_documents.append({
                "title": item["value"],
                "field": item["field"],
                "published_at": item.get("published_at"),
            })

    # Sort ir_documents by published_at descending (None last)
    ir_documents.sort(key=lambda x: (x["published_at"] is not None, x.get("published_at", "") or ""), reverse=True)

    # Current price: latest close from market_data
    current_price = None
    market_close_items = [
        item for item in evidence
        if item.get("kind") == "market_data" and item.get("field") == "close"
    ]
    if market_close_items:
        market_close_items.sort(
            key=lambda x: x.get("period_end", ""),
            reverse=True,
        )
        current_price = market_close_items[0].get("value")

    # latest_market: flattened from market_metrics
    mm = market_metrics or {}
    latest_market = {
        "rsi": _nested_get(mm, "rsi", "latest"),
        "sma_25": _nested_get(mm, "moving_averages", "sma_25"),
        "sma_75": _nested_get(mm, "moving_averages", "sma_75"),
        "price_vs_sma25_pct": _nested_get(mm, "moving_averages", "price_vs_sma25_pct"),
        "price_vs_sma75_pct": _nested_get(mm, "moving_averages", "price_vs_sma75_pct"),
        "bollinger_upper": _nested_get(mm, "bollinger", "upper"),
        "bollinger_middle": _nested_get(mm, "bollinger", "middle"),
        "bollinger_lower": _nested_get(mm, "bollinger", "lower"),
        "bollinger_position_pct": _nested_get(mm, "bollinger", "position_pct"),
        "volatility_annual_pct": _nested_get(mm, "volatility", "annual_sigma_pct"),
        "max_drawdown_pct": _nested_get(mm, "volatility", "max_drawdown_pct"),
        "return_20d_pct": _nested_get(mm, "returns", "return_20d_pct"),
        "total_return_pct": _nested_get(mm, "returns", "total_return_pct"),
        "macd_line": _nested_get(mm, "macd", "macd_line"),
        "macd_signal": _nested_get(mm, "macd", "signal"),
        "macd_histogram": _nested_get(mm, "macd", "histogram"),
        "volume_latest": _nested_get(mm, "volume", "latest"),
        "volume_ratio_vs_avg": _nested_get(mm, "volume", "ratio_vs_avg"),
    }

    return {
        "company_profile": company_profile,
        "performance": performance,
        "company_scores": company_scores,
        "current_price": current_price,
        "latest_market": latest_market,
        "ir_documents": ir_documents,
        "data_quality": evidence_pack.get("data_quality", {}),
        "evidence_counts": evidence_counts,
    }


def _nested_get(d: dict, *keys):
    """Safely traverse nested dicts returning None for missing keys."""
    for key in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d
