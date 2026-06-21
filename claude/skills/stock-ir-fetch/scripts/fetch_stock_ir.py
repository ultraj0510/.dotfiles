"""Orchestrate official IR source sync: discovery -> approval -> crawl -> fetch -> store."""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from document_classifier import classify_document
from document_extractor import extract_document, TesseractOcrEngine
from document_fetcher import fetch_document
from document_index import scan_index
from document_store import DocumentStore, document_id
from safe_http import SafeHttpClient, registrable_domain
from source_discovery import (
    YahooCompanyMetadataProvider,
    discover_candidates,
    validate_user_source,
)
from source_registry import SourceRegistry
from ticker import normalize_ticker, to_yahoo_symbol


JST = ZoneInfo("Asia/Tokyo")
DEFAULT_DATA_DIR = Path("/Users/fujie/code/runtime/stock-company-analysis")


def _empty_manifest(ticker, now, status, errors=None):
    return {
        "schema_version": "1.0",
        "run_id": f"{now.strftime('%Y%m%dT%H%M%S%z')}-{ticker}",
        "ticker": ticker,
        "as_of": now.isoformat(),
        "status": status,
        "sync": {"mode": "none", "window_start": None, "window_end": None,
                 "index_url": "", "visited_pages": [], "index_parse_status": ""},
        "documents": [],
        "errors": errors or [],
        "summary": {
            "discovered": 0, "new_documents": 0, "new_versions": 0,
            "unchanged": 0, "no_longer_listed": 0, "fetch_errors": 0,
            "extraction_errors": 0, "usable": False,
        },
    }


def fetch_stock_ir(ticker, data_dir=DEFAULT_DATA_DIR, now=None, refresh=False,
                   approve_candidate=None, approve_url=None, dependencies=None):
    deps = dependencies or {}
    now = (now or datetime.now(JST)).astimezone(JST)
    normalized = normalize_ticker(ticker)
    if normalized is None:
        return _empty_manifest(ticker, now, "failed", [{"section": "_global", "code": "ticker_invalid", "message": "Invalid ticker"}])

    data_dir = Path(data_dir)
    store = deps.get("store") or DocumentStore(data_dir)
    registry = deps.get("registry") or SourceRegistry(data_dir)
    source = registry.load(normalized)
    http = deps.get("http_client") or SafeHttpClient()
    meta_provider = deps.get("metadata_provider") or YahooCompanyMetadataProvider()
    ocr = deps.get("ocr_engine") or TesseractOcrEngine()

    # Approval flow
    if approve_candidate or approve_url:
        if approve_candidate and approve_url:
            return _empty_manifest(normalized, now, "failed", [{"section": "_global", "code": "mutually_exclusive", "message": "Only one approval method"}])
        if approve_url:
            meta = meta_provider.lookup(normalized)
            source = validate_user_source(normalized, approve_url, meta.get("company_name", ""), http)
            if not source:
                return _empty_manifest(normalized, now, "confirmation_required", [{"section": "_global", "code": "url_rejected", "message": "URL could not be validated"}])
            registry.approve(normalized, source, now)
            source = registry.load(normalized)
        else:
            candidates = discover_candidates(normalized, meta_provider, http)
            match = [c for c in candidates if c["candidate_id"] == approve_candidate]
            if not match:
                return _empty_manifest(normalized, now, "confirmation_required", [{"section": "_global", "code": "candidate_not_found", "message": f"Candidate {approve_candidate} not found"}])
            source = registry.approve(normalized, match[0], now)

    if not source:
        candidates = discover_candidates(normalized, meta_provider, http)
        if candidates:
            return {
                "schema_version": "1.0",
                "ticker": normalized,
                "status": "confirmation_required",
                "candidates": candidates,
                "requested_input": "候補IDを承認するか、公式IR資料一覧のHTTPS URLを指定してください",
                "errors": [],
            }
        else:
            return _empty_manifest(normalized, now, "confirmation_required", [{"section": "_global", "code": "no_candidates", "message": "No IR candidates found"}])

    # Determine window
    prev_manifest = None if refresh else store.load_manifest(normalized)
    if prev_manifest and prev_manifest.get("status") in ("success", "partial"):
        window_start = (now - timedelta(days=90)).date()
        mode = "incremental"
    else:
        try:
            window_start = now.replace(year=now.year - 3).date()
        except ValueError:
            window_start = now.replace(year=now.year - 3, day=28).date()
        mode = "initial"

    window_end = now.date()
    domain = source["approved_domain"]
    index_url = source["document_index_url"]
    allowed = {domain}

    scan = scan_index(index_url, window_start, window_end, domain, http)
    if scan["status"] == "error":
        return _empty_manifest(normalized, now, "failed", [{"section": "index", "code": "index_fetch_failed", "message": "All index pages failed to fetch"}])
    if scan["status"] == "unsupported":
        result = _empty_manifest(normalized, now, "unsupported",
            [{"section": "index", "code": "unsupported", "message": "Static HTML index not supported"}])
        result["sync"]["mode"] = mode
        result["sync"]["window_start"] = window_start.isoformat()
        result["sync"]["window_end"] = window_end.isoformat()
        store.save_manifest(normalized, result)
        registry.update_sync_times(normalized, now, None)
        return result
    # Collect delivery domains from index entries
    delivery_domains = set()
    for entry in scan["entries"]:
        parsed = urlparse(entry["url"])
        host = parsed.hostname or ""
        entry_domain = registrable_domain(host)
        if entry_domain and entry_domain != domain:
            delivery_domains.add(entry_domain)

    # Merge with previous manifest
    prev_docs = {}
    if prev_manifest:
        for doc in prev_manifest.get("documents", []):
            prev_docs[doc["document_id"]] = doc

    manifest = {
        "schema_version": "1.0",
        "run_id": f"{now.strftime('%Y%m%dT%H%M%S%z')}-{normalized}",
        "ticker": normalized,
        "as_of": now.isoformat(),
        "status": "success",
        "sync": {
            "mode": mode,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "index_url": index_url,
            "visited_pages": scan["visited_pages"],
            "index_parse_status": scan["status"] if scan["complete"] else "incomplete",
        },
        "documents": [],
        "errors": list(prev_manifest.get("errors", [])) if prev_manifest else [],
        "summary": {
            "discovered": len(scan["entries"]),
            "new_documents": 0, "new_versions": 0, "unchanged": 0,
            "no_longer_listed": 0, "fetch_errors": 0, "extraction_errors": 0,
            "usable": False,
        },
    }

    current_doc_ids = set()
    for entry in scan["entries"]:
        category = classify_document(entry["title"], entry.get("context", ""))
        if category is None:
            continue

        fetched, fetch_err = fetch_document(entry["url"], allowed, delivery_domains, http)
        if fetch_err:
            manifest["errors"].append({"url": entry["url"], "code": fetch_err["code"], "message": fetch_err["message"]})
            manifest["summary"]["fetch_errors"] += 1
            continue

        extraction = extract_document(fetched["body"], fetched["extension"], now, ocr)
        if extraction.get("error"):
            manifest["errors"].append({"url": entry["url"], "code": extraction["error"]["code"], "message": extraction["error"]["message"]})
            manifest["summary"]["extraction_errors"] += 1

        version_info, is_new_version = store.save_version(normalized, entry, fetched, extraction, now)
        doc_id = version_info["document_id"]
        current_doc_ids.add(doc_id)

        if is_new_version:
            if version_info["is_new_document"]:
                manifest["summary"]["new_documents"] += 1
            else:
                manifest["summary"]["new_versions"] += 1
        else:
            manifest["summary"]["unchanged"] += 1

        manifest["documents"].append({
            "document_id": doc_id,
            "sha256": fetched["sha256"],
            "category": category,
            "title": entry["title"],
            "published_at": entry["published_at"],
        })

    # Carry forward documents from previous manifest
    for doc_id, doc in prev_docs.items():
        if doc_id not in current_doc_ids:
            # Only mark as no_longer_listed if doc was published within current window
            pub = doc.get("published_at", "")
            in_window = False
            if pub:
                try:
                    pub_date = date.fromisoformat(pub)
                    in_window = window_start <= pub_date <= window_end
                except ValueError:
                    pass
            if scan["complete"] and in_window:
                doc["listing_status"] = "no_longer_listed"
                manifest["documents"].append(doc)
                manifest["summary"]["no_longer_listed"] += 1
            else:
                # Outside window or incomplete scan — preserve unchanged
                doc["listing_status"] = doc.get("listing_status", "listed")
                manifest["documents"].append(doc)
                manifest["summary"]["unchanged"] += 1
        else:
            old = prev_docs[doc_id]
            if old.get("listing_status") == "no_longer_listed":
                pass  # current version already added with listed status

    if not scan["complete"]:
        manifest["status"] = "partial"
    if scan["errors"]:
        manifest["status"] = "partial"
    if manifest["summary"]["fetch_errors"] > 0 or manifest["summary"]["extraction_errors"] > 0:
        manifest["status"] = "partial"
    if scan["status"] == "error":
        manifest["status"] = "failed"
    if not manifest["documents"] and not scan["entries"]:
        manifest["status"] = "unsupported"
    manifest["summary"]["usable"] = (
        len(manifest["documents"]) > 0
        and scan["complete"]
    )

    store.save_manifest(normalized, manifest)
    success_time = now if (manifest["status"] in ("success", "partial") and scan["complete"]) else None
    registry.update_sync_times(normalized, now, success_time)

    return manifest


def _parser():
    parser = argparse.ArgumentParser(prog="stock-ir-fetch")
    parser.add_argument("ticker")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--approve-source", dest="approve_candidate", default=None)
    parser.add_argument("--approve-source-url", dest="approve_url", default=None)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    result = fetch_stock_ir(
        args.ticker, args.data_dir, refresh=args.refresh,
        approve_candidate=args.approve_candidate,
        approve_url=args.approve_url,
    )
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    sys.stdout.write("\n")
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
