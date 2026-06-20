"""stock-info-fetch: SBI securities 1 ticker investment fact data fetch and JSON output.

Usage:
    fetch_stock_info.py <ticker> [--refresh] [--cache-dir PATH]

Output: JSON to stdout. Logs/warnings to stderr.
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from page_state import classify_page_state, visible_soup

PORTFOLIO_CORE = Path.home() / ".dotfiles" / "portfolio-core"
if str(PORTFOLIO_CORE) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_CORE))

from cache_manager import CacheManager
from http_client import SafeHttpClient
from source_urls import (
    build_detail_url,
    extract_analysis_sources,
    extract_stock_report_pdf_url,
)
from sbi_stock_parser import (
    ticker_is_valid,
    parse_price,
    parse_company_profile,
    parse_news,
    parse_disclosures,
    parse_company_scores,
    parse_performance,
)
from pdf_parser import parse_stock_report_pdf

JST = timezone(timedelta(hours=9))
_GLOBAL_ERRORS = {"auth_unset", "auth_expired", "ticker_invalid", "ticker_not_found"}


def fetch_stock_info(ticker: str, refresh: bool = False,
                     cache_dir: Path | None = None) -> dict:
    """Main orchestrator. Fetches all 7 sections, returns assembled JSON dict."""

    # 1. Validate ticker
    if not ticker_is_valid(ticker):
        return _error_result(ticker, "ticker_invalid", f"Invalid ticker: {ticker}")

    # 2. Check cache
    cm = CacheManager(cache_dir)
    if not refresh:
        cached = cm.get(ticker)
        if cached:
            print(f"[INFO] Cache hit for {ticker}", file=sys.stderr)
            return cached

    # 3. Read cookie (lazy import -- allows tests to mock sys.modules before first call)
    import cookie_store
    bundle = cookie_store.read_cookie_bundle()
    cookie_header = bundle.get("cookie_header", "")
    if not cookie_header:
        return _error_result(ticker, "auth_unset", "No SBI cookie available")
    print("[INFO] SBI authentication loaded", file=sys.stderr)

    now_iso = datetime.now(JST).isoformat()
    result = {
        "schema_version": "1.0",
        "ticker": ticker,
        "company_name": "",
        "fetched_at": now_iso,
        "cache": {"hit": False, "date": datetime.now(JST).strftime("%Y-%m-%d")},
        "sections": {},
        "errors": [],
    }
    client = SafeHttpClient()

    # 4. Fetch direct tab sections
    tab_sections = {
        "price": ("price", parse_price),
        "company_profile": ("company_profile", parse_company_profile),
        "news": ("news", parse_news),
    }

    for section_key, (tab_name, parser) in tab_sections.items():
        fetched = client.fetch_html(build_detail_url(ticker, tab_name), cookie_header)
        if fetched.status == "auth_expired":
            return _global_error_result(ticker, "auth_expired")
        if fetched.status != "ok":
            _add_error(result, section_key, fetched.status, f"Failed to fetch {tab_name}", fetched.url)
            continue
        html = _decode_html(fetched.body)
        global_code = classify_page_state(html, fetched.url)
        if global_code:
            return _global_error_result(ticker, global_code)

        parsed = parser(html)
        _set_section(result, section_key, parsed, fetched.url, now_iso)

    # 5. Analysis tab -> scores + performance + disclosures
    analysis_fetch = client.fetch_html(build_detail_url(ticker, "analysis"), cookie_header)
    if analysis_fetch.status == "auth_expired":
        return _global_error_result(ticker, "auth_expired")
    if analysis_fetch.status == "ok":
        html = _decode_html(analysis_fetch.body)
        global_code = classify_page_state(html, analysis_fetch.url)
        if global_code:
            return _global_error_result(ticker, global_code)
        sources = extract_analysis_sources(html, analysis_fetch.url)
        score_html = ""
        score_fetch_ok = False

        # 5a. Company scores via iframe (NO cookie!)
        if sources.score_url:
            score_fetch = client.fetch_html(sources.score_url)  # no cookie_header!
            if score_fetch.status == "ok":
                score_html = _decode_html(score_fetch.body)
                score_fetch_ok = True
                parsed = parse_company_scores(score_html)
                _set_section(result, "company_scores", parsed, score_fetch.url, now_iso)
            else:
                _add_error(result, "company_scores", score_fetch.status,
                           "Failed to fetch company scores iframe", score_fetch.url)
        elif _has_not_available_marker(html, "スコア情報はありません", "企業スコアはありません"):
            result["sections"]["company_scores"] = {
                "status": "not_available", "data": {},
                "source": {"url": analysis_fetch.url, "fetched_at": now_iso},
            }
        else:
            _add_error(result, "company_scores", "source_changed",
                       "Score iframe URL is missing", analysis_fetch.url)

        # 5b. Performance via onclick popup url (cookie IS sent -- sbisec host)
        if sources.performance_entry_url:
            perf_fetch = client.fetch_html(sources.performance_entry_url, cookie_header)
            if perf_fetch.status == "auth_expired":
                return _global_error_result(ticker, "auth_expired")
            if perf_fetch.status == "ok":
                perf_html = _decode_html(perf_fetch.body)
                global_code = classify_page_state(perf_html, perf_fetch.url)
                if global_code:
                    return _global_error_result(ticker, global_code)
                parsed = parse_performance(perf_html)
                _set_section(result, "performance", parsed, perf_fetch.url, now_iso)
            else:
                _add_error(result, "performance", perf_fetch.status,
                           "Failed to fetch STOCK REPORTS HTML", perf_fetch.url)
        elif _has_not_available_marker(html, "業績情報はありません"):
            result["sections"]["performance"] = {
                "status": "not_available", "data": {},
                "source": {"url": analysis_fetch.url, "fetched_at": now_iso},
            }
        else:
            _add_error(result, "performance", "source_changed",
                       "Performance popup URL is missing", analysis_fetch.url)

        # 5c. Stock Reports PDF from score iframe HTML (NO cookie!)
        pdf_url = (
            extract_stock_report_pdf_url(score_html, sources.score_url)
            if sources.score_url and score_html
            else None
        )
        if pdf_url:
            pdf_result = _fetch_and_parse_pdf(client, pdf_url)
            _set_section(result, "stock_reports", pdf_result, pdf_result.get("url", ""), now_iso)
        elif sources.score_url is None:
            # Score iframe missing — check for explicit marker before calling it changed.
            if _has_not_available_marker(html, "スコア情報はありません", "企業スコアはありません"):
                result["sections"]["stock_reports"] = {
                    "status": "not_available", "data": {},
                    "source": {"url": analysis_fetch.url, "fetched_at": now_iso},
                }
            else:
                _add_error(result, "stock_reports", "source_changed",
                           "Score iframe not found in analysis page", analysis_fetch.url)
        elif score_fetch_ok:
            # Score page was fetched, check for explicit not-available marker
            if _has_not_available_marker(score_html, "STOCK REPORTSはありません", "レポートはありません"):
                result["sections"]["stock_reports"] = {
                    "status": "not_available", "data": {},
                    "source": {"url": analysis_fetch.url, "fetched_at": now_iso},
                }
            else:
                _add_error(result, "stock_reports", "source_changed",
                           "PDF link not found in score page", score_fetch.url)
        else:
            _add_error(result, "stock_reports",
                       "fetch_failed",
                       "Cannot check STOCK REPORTS PDF: score page unavailable",
                       "")

        # 5d. Disclosures via onclick popup url (cookie IS sent -- sbisec host)
        if sources.disclosures_entry_url:
            disc_fetch = client.fetch_html(sources.disclosures_entry_url, cookie_header)
            if disc_fetch.status == "auth_expired":
                return _global_error_result(ticker, "auth_expired")
            if disc_fetch.status == "ok":
                disc_html = _decode_html(disc_fetch.body)
                global_code = classify_page_state(disc_html, disc_fetch.url)
                if global_code:
                    return _global_error_result(ticker, global_code)
                parsed = parse_disclosures(disc_html)
                _set_section(result, "disclosures", parsed, disc_fetch.url, now_iso)
            else:
                _add_error(result, "disclosures", disc_fetch.status,
                           "Failed to fetch disclosures", disc_fetch.url)
        elif _has_not_available_marker(html, "適時開示はありません"):
            result["sections"]["disclosures"] = {
                "status": "not_available", "data": {},
                "source": {"url": analysis_fetch.url, "fetched_at": now_iso},
            }
        else:
            _add_error(result, "disclosures", "source_changed",
                       "Disclosure popup URL is missing", analysis_fetch.url)
    elif analysis_fetch.status == "auth_expired":
        return _global_error_result(ticker, "auth_expired")
    else:
        for sec in ["company_scores", "performance", "stock_reports", "disclosures"]:
            _add_error(result, sec, analysis_fetch.status,
                       f"Analysis tab unavailable: {analysis_fetch.status}", analysis_fetch.url)

    # Extract company_name from profile if available
    profile = result["sections"].get("company_profile", {})
    if profile.get("status") == "ok":
        result["company_name"] = profile.get("data", {}).get("company_name", "")

    # Save to cache (even partial results)
    cm.save(ticker, result)
    return result


def _add_error(result: dict, section: str, code: str, message: str, url: str = "") -> None:
    if section not in result["sections"]:
        result["sections"][section] = {
            "status": "error", "data": {},
            "source": {"url": url, "fetched_at": result.get("fetched_at", "")},
        }
    result["sections"][section]["status"] = "error"
    result["errors"].append({"section": section, "code": code, "message": message})


def _set_section(result: dict, section_key: str, parsed: dict, url: str, now_iso: str) -> None:
    """Write a parsed section into the result, normalizing status to ok/not_available/error."""
    status = parsed["status"]
    if status not in ("ok", "not_available"):
        status = "error"
    result["sections"][section_key] = {
        "status": status,
        "data": parsed["data"],
        "source": {"url": url, "fetched_at": now_iso},
    }
    if parsed["status"] == "source_changed":
        _add_error(result, section_key, "source_changed",
                   f"Structure changed for {section_key}", url)
    elif parsed["status"] == "error":
        _add_error(result, section_key,
                   parsed.get("error_code", "parse_failed"),
                   parsed.get("message", f"Failed to parse {section_key}"),
                   url)


def _error_result(ticker: str, code: str, message: str) -> dict:
    now_iso = datetime.now(JST).isoformat()
    return {
        "schema_version": "1.0",
        "ticker": ticker,
        "company_name": "",
        "fetched_at": now_iso,
        "cache": {"hit": False, "date": datetime.now(JST).strftime("%Y-%m-%d")},
        "sections": {},
        "errors": [{"section": "_global", "code": code, "message": message}],
    }


def _global_error_result(ticker: str, code: str) -> dict:
    messages = {
        "auth_expired": "SBI session expired",
        "ticker_not_found": f"Ticker {ticker} not found",
    }
    return _error_result(ticker, code, messages.get(code, code))


def _has_not_available_marker(html: str, *markers: str) -> bool:
    """Check if any explicit 'not available' marker appears in visible text only."""
    return any(m in visible_soup(html).get_text(" ", strip=True) for m in markers)


def _decode_html(body: bytes | None) -> str:
    if not body:
        return ""
    for encoding in ("utf-8", "cp932", "shift_jis"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("cp932", errors="replace")


def _fetch_and_parse_pdf(client: SafeHttpClient, pdf_url: str) -> dict:
    import tempfile
    from url_cleaner import clean_url

    cleaned = clean_url(pdf_url)
    fetched = client.fetch_bytes(pdf_url)  # NO cookie!
    if fetched.status != "ok" or not fetched.body:
        return {"status": "error", "data": {}, "url": cleaned,
                "error_code": fetched.status, "message": "PDF fetch failed"}
    if fetched.content_type != "application/pdf" or not fetched.body.startswith(b"%PDF"):
        return {"status": "error", "data": {}, "url": cleaned,
                "error_code": "pdf_unavailable", "message": "Response is not a PDF"}

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(fetched.body)
        tmp_path = tmp.name

    try:
        result = parse_stock_report_pdf(tmp_path)
        result["url"] = cleaned
        return result
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


def main(cli_args: list[str] | None = None):
    import argparse

    class _JsonErrorParser(argparse.ArgumentParser):
        def error(self, message):
            result = _error_result("unknown", "usage_error", message)
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
            sys.exit(1)

    parser = _JsonErrorParser(
        description="SBI securities from designated ticker investment fact data retrieval"
    )
    parser.add_argument("ticker", help="Domestic stock code (example: 3932)")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache and re-fetch")
    parser.add_argument("--cache-dir", help="Cache directory (default: ~/.claude/cache/stock-info-fetch)")
    args = parser.parse_args(cli_args)

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    try:
        result = fetch_stock_info(args.ticker, refresh=args.refresh, cache_dir=cache_dir)
    except Exception:
        result = _error_result(args.ticker, "internal_error", "Unexpected internal failure")
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        sys.exit(1)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    global_errors = [e for e in result.get("errors", []) if e["section"] == "_global"]
    if global_errors:
        code = global_errors[0]["code"]
        sys.exit(2 if code in ("auth_expired", "auth_unset") else 1)


if __name__ == "__main__":
    main()
