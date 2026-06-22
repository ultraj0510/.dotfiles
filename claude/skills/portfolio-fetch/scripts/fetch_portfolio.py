#!/usr/bin/env python3
"""Fetch SBI portfolio facts and print a raw JSON snapshot."""

import argparse
import json
import os
import sys

import yaml

_STOCK_ANALYZE_DIR = os.path.expanduser("~/code/playground/stock-price-analyze")
_DEFAULT_PORTFOLIO_PATH = os.path.join(_STOCK_ANALYZE_DIR, "portfolio.yaml")


def _print_json(snapshot: dict) -> None:
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=False))


def _build_snapshot(data: dict, sync_status: str, cache_used: bool) -> dict:
    """Build JSON snapshot from portfolio YAML data.

    YAML stores ``last_updated`` / ``last_sync_source`` for backward
    compatibility; the JSON output maps them to ``fetched_at`` / ``source``.
    """
    return {
        "fetched_at": data.get("last_updated"),
        "source": data.get("last_sync_source", "SBI"),
        "sync_status": sync_status,
        "cache_used": cache_used,
        "account": data.get("account", {}),
        "holdings": data.get("holdings", []),
    }


def _load_cache_or_exit(portfolio_path: str, status: str) -> None:
    try:
        with open(portfolio_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"[ERROR] portfolio.yaml not found at {portfolio_path}", file=sys.stderr)
        sys.exit(1)

    _print_json(_build_snapshot(data, sync_status=status, cache_used=True))


def main():
    parser = argparse.ArgumentParser(description="Fetch raw SBI portfolio data")
    parser.add_argument("--skip-sync", action="store_true", help="Do not contact SBI; print cached portfolio.yaml as JSON")
    parser.add_argument("--use-cache-on-fail", action="store_true", help="Print cached data if SBI fetch fails")
    parser.add_argument("--portfolio-path", default=_DEFAULT_PORTFOLIO_PATH, help="portfolio.yaml path")
    args = parser.parse_args()

    if args.skip_sync:
        _load_cache_or_exit(args.portfolio_path, status="cache")
        return

    from sbi_fetch import sync_from_sbi

    status = sync_from_sbi(args.portfolio_path)

    if status == "ok":
        with open(args.portfolio_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _print_json(_build_snapshot(data, sync_status="ok", cache_used=False))
        return

    if args.use_cache_on_fail:
        print(f"[NOTICE] SBI fetch failed; using cached portfolio data (status: {status})", file=sys.stderr)
        _load_cache_or_exit(args.portfolio_path, status=status)
        return

    if status in ("no_cookie", "auth_expired"):
        print("[AUTH_EXPIRED] SBIセッションが切れています。", file=sys.stderr)
        sys.exit(2)

    print(f"[ERROR] SBIデータ取得に失敗しました ({status})。", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
