#!/usr/bin/env python3
"""Fetch SBI portfolio facts and print a raw JSON snapshot."""

import argparse
import json
import os
import sys


_STOCK_ANALYZE_DIR = os.path.expanduser("~/code/playground/stock-price-analyze")
_DEFAULT_PORTFOLIO_PATH = os.path.join(_STOCK_ANALYZE_DIR, "portfolio.yaml")


def _print_json(snapshot: dict) -> None:
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=False))


def _load_cache_or_exit(portfolio_path: str, status: str):
    from sbi_fetch import load_cached_snapshot

    try:
        snapshot = load_cached_snapshot(portfolio_path, status=status)
    except FileNotFoundError:
        print(f"[ERROR] portfolio.yaml not found at {portfolio_path}", file=sys.stderr)
        sys.exit(1)
    _print_json(snapshot)


def main():
    parser = argparse.ArgumentParser(description="Fetch raw SBI portfolio data")
    parser.add_argument("--skip-sync", action="store_true", help="Do not contact SBI; print cached portfolio.yaml as JSON")
    parser.add_argument("--use-cache-on-fail", action="store_true", help="Print cached data if SBI fetch fails")
    parser.add_argument("--portfolio-path", default=_DEFAULT_PORTFOLIO_PATH, help="portfolio.yaml path")
    args = parser.parse_args()

    if args.skip_sync:
        _load_cache_or_exit(args.portfolio_path, status="cache")
        return

    from sbi_fetch import fetch_raw_snapshot

    snapshot, status = fetch_raw_snapshot(args.portfolio_path)
    if status == "ok":
        _print_json(snapshot)
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
