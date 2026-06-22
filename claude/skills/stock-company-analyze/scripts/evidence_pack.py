"""Build and validate evidence-pack.json."""
import hashlib
import json


def build_evidence_pack(ticker, company_name, as_of, info_result, price_result, ir_result, market_metrics):
    run_id = f"{as_of.strftime('%Y%m%dT%H%M%S%z')}-{ticker}"
    evidence = []

    if price_result.parsed:
        price_data = price_result.parsed.get("data", {})
        daily = price_data.get("daily", {})
        for bar in daily.get("bars", []):
            for field in ("open", "high", "low", "close", "volume"):
                if field in bar:
                    evidence.append({
                        "evidence_id": f"price-{bar['date']}-{field}",
                        "kind": "market_data",
                        "field": field,
                        "value": bar[field],
                        "unit": "JPY" if field != "volume" else "shares",
                        "period_end": bar["date"],
                        "source_type": "stock-price-fetch",
                        "source_ref": f"daily:{bar['date']}",
                        "usable": True,
                    })

    if info_result.parsed:
        info = info_result.parsed
        # stock-info-fetch schema 1.1: top-level company_name + sections dict
        sections = info.get("sections", {})
        # Company profile
        profile = sections.get("company_profile", {})
        if isinstance(profile, dict):
            for key, val in profile.items():
                if val is not None and key not in ("raw_html",):
                    evidence.append({
                        "evidence_id": f"info-profile-{_safe_id(key)}",
                        "kind": "fundamentals",
                        "field": key,
                        "value": val,
                        "unit": None,
                        "source_type": "stock-info-fetch",
                        "source_ref": f"company_profile:{key}",
                        "usable": True,
                    })
        # Performance/earnings data
        perf = sections.get("performance", {})
        if isinstance(perf, dict):
            perf_data = perf.get("data", {})
            if isinstance(perf_data, dict):
                for key, val in perf_data.items():
                    if val is not None:
                        evidence.append({
                            "evidence_id": f"info-perf-{_safe_id(key)}",
                            "kind": "fundamentals",
                            "field": key,
                            "value": val,
                            "unit": None,
                            "source_type": "stock-info-fetch",
                            "source_ref": f"performance:{key}",
                            "usable": True,
                        })
        # Company scores
        scores = sections.get("company_scores", {})
        if isinstance(scores, dict):
            scores_data = scores.get("data", {})
            if isinstance(scores_data, dict):
                for key, val in scores_data.items():
                    if val is not None:
                        evidence.append({
                            "evidence_id": f"info-score-{_safe_id(key)}",
                            "kind": "fundamentals",
                            "field": key,
                            "value": val,
                            "unit": None,
                            "source_type": "stock-info-fetch",
                            "source_ref": f"company_scores:{key}",
                            "usable": True,
                        })

    if ir_result.parsed:
        for doc in ir_result.parsed.get("documents", []):
            evidence.append({
                "evidence_id": f"ir-{doc['document_id']}",
                "kind": "ir_document",
                "field": doc.get("category", "other"),
                "value": doc.get("title", ""),
                "unit": None,
                "published_at": doc.get("published_at"),
                "source_type": "stock-ir-fetch",
                "source_ref": f"ir:{doc['document_id']}",
                "usable": True,
            })

    pack = {
        "schema_version": "1.0",
        "run_id": run_id,
        "ticker": ticker,
        "company_name": company_name,
        "as_of": as_of.isoformat(),
        "source_runs": {
            "stock_info_fetch": _source_summary(info_result),
            "stock_price_fetch": _source_summary(price_result),
            "stock_ir_fetch": _source_summary(ir_result),
        },
        "evidence": evidence,
        "data_quality": _data_quality(ir_result),
        "sha256": "",
    }
    pack["sha256"] = compute_sha256(pack)
    return pack


def validate_evidence_pack(pack):
    errors = []
    if not isinstance(pack, dict):
        return ["pack must be a dict"]
    if pack.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    if not pack.get("ticker"):
        errors.append("ticker is required")
    if not pack.get("as_of"):
        errors.append("as_of is required")
    if not isinstance(pack.get("evidence"), list):
        errors.append("evidence must be a list")
    sha = pack.get("sha256", "")
    if not sha or len(sha) != 64:
        errors.append("sha256 must be 64-char hex")
    return errors


def compute_sha256(pack):
    payload = {k: v for k, v in pack.items() if k != "sha256"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _safe_id(text):
    import re
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(text))[:60]


def _source_summary(result):
    if result is None:
        return {"status": "not_run"}
    parsed = result.parsed
    if parsed is None:
        return {"status": "parse_error", "exit_code": result.exit_code}
    return {
        "status": parsed.get("status", "unknown"),
        "run_id": parsed.get("run_id"),
        "as_of": parsed.get("as_of"),
    }


def _data_quality(ir_result):
    if ir_result and ir_result.parsed:
        summary = ir_result.parsed.get("summary", {})
        return {
            "coverage_complete": summary.get("coverage_complete", False),
            "prohibited_documents": summary.get("prohibited_documents", 0),
            "dynamic_pages": summary.get("dynamic_pages", 0),
        }
    return {"coverage_complete": False, "prohibited_documents": 0, "dynamic_pages": 0}
