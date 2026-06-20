from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from price_series import (
    PriceDataError,
    has_new_corporate_action,
    merge_bars,
    normalize_daily,
    normalize_intraday,
)
from price_store import PriceStore
from ticker import normalize_ticker, to_provider_symbol
from yahoo_provider import PriceProviderError, YahooPriceProvider


JST = ZoneInfo("Asia/Tokyo")
DEFAULT_DATA_DIR = Path("/Users/fujie/code/runtime/stock-company-analysis")


def _five_year_start(now):
    try:
        return now.replace(year=now.year - 5)
    except ValueError:
        return now.replace(year=now.year - 5, day=28)


def _error(code, message, retryable=False):
    return {"code": code, "message": message, "retryable": retryable}


def _empty_series(status="not_available", fetched_at=""):
    return {"status": status, "fetched_at": fetched_at, "data_as_of": None, "bars": []}


def _series_result(bars, status, fetched_at):
    return {
        "status": status,
        "fetched_at": fetched_at,
        "data_as_of": bars[-1]["date"] if bars else None,
        "bars": bars,
    }


def _intraday_series_result(bars, status, fetched_at):
    return {
        "status": status,
        "fetched_at": fetched_at,
        "data_as_of": bars[-1]["timestamp"] if bars else None,
        "bars": bars,
    }


def _failed_result(raw_ticker, now, code, message):
    return {
        "schema_version": "1.1",
        "run_id": f"{now.strftime('%Y%m%dT%H%M%S%z')}-invalid",
        "ticker": "",
        "provider_symbol": "",
        "as_of": now.isoformat(),
        "status": "failed",
        "sync": {
            "mode": "none",
            "daily_requested_from": None,
            "intraday_requested_from": None,
            "reconcile_reason": None,
        },
        "data": {
            "exchange_timezone": "Asia/Tokyo",
            "currency": "JPY",
            "daily": _empty_series(),
            "intraday_1h": _empty_series(),
        },
        "sources": {},
        "errors": [_error(code, message)],
        "summary": {
            "daily_rows": 0,
            "intraday_rows": 0,
            "daily_first_date": None,
            "daily_last_date": None,
            "intraday_first_timestamp": None,
            "intraday_last_timestamp": None,
            "usable": False,
        },
    }


def _build_summary(daily_series, intraday_series, minimum_daily_rows):
    daily_bars = daily_series["bars"]
    intraday_bars = intraday_series["bars"]
    return {
        "daily_rows": len(daily_bars),
        "intraday_rows": len(intraday_bars),
        "daily_first_date": daily_bars[0]["date"] if daily_bars else None,
        "daily_last_date": daily_bars[-1]["date"] if daily_bars else None,
        "intraday_first_timestamp": intraday_bars[0]["timestamp"] if intraday_bars else None,
        "intraday_last_timestamp": intraday_bars[-1]["timestamp"] if intraday_bars else None,
        "usable": len(daily_bars) >= minimum_daily_rows,
    }


def _daily_start(existing_bars, now):
    if not existing_bars:
        return _five_year_start(now)
    last = datetime.fromisoformat(existing_bars[-1]["date"]).replace(tzinfo=JST)
    return last - timedelta(days=10)


def _intraday_start(existing_bars, now):
    if not existing_bars:
        return now - timedelta(days=60)
    return datetime.fromisoformat(existing_bars[-1]["timestamp"]) - timedelta(hours=2)


def _build_payload(ticker, symbol, now, mode, daily_start, intraday_start,
                   daily_series, intraday_series, errors, reconcile_reason, minimum_daily_rows):
    status = "success" if not errors else "partial"
    summary = _build_summary(daily_series, intraday_series, minimum_daily_rows)
    if not daily_series["bars"] and not intraday_series["bars"]:
        status = "failed"
    return {
        "schema_version": "1.1",
        "run_id": f"{now.strftime('%Y%m%dT%H%M%S%z')}-{ticker}",
        "ticker": ticker,
        "provider_symbol": symbol,
        "as_of": now.isoformat(),
        "status": status,
        "sync": {
            "mode": mode,
            "daily_requested_from": daily_start.date().isoformat(),
            "intraday_requested_from": intraday_start.isoformat(),
            "reconcile_reason": reconcile_reason,
        },
        "data": {
            "exchange_timezone": "Asia/Tokyo",
            "currency": "JPY",
            "daily": daily_series,
            "intraday_1h": intraday_series,
        },
        "sources": {
            "daily": {
                "provider": "yahoo_finance",
                "symbol": symbol,
                "fetched_at": daily_series["fetched_at"],
            },
            "intraday_1h": {
                "provider": "yahoo_finance",
                "symbol": symbol,
                "fetched_at": intraday_series["fetched_at"],
            },
        },
        "errors": errors,
        "summary": summary,
    }


def fetch_stock_price(
    ticker,
    data_dir=DEFAULT_DATA_DIR,
    now=None,
    refresh=False,
    provider=None,
    minimum_daily_rows=200,
):
    now = now or datetime.now(JST)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(JST)
    normalized = normalize_ticker(ticker)
    if normalized is None:
        return _failed_result(ticker, now, "ticker_invalid", "Invalid ticker format")

    symbol = to_provider_symbol(normalized)
    store = PriceStore(data_dir)

    # Always load previous as safety net (P1#1: refresh no longer discards)
    previous = store.load(normalized)
    prev_daily = previous["data"]["daily"] if previous else None
    prev_intraday = previous["data"]["intraday_1h"] if previous else None

    old_daily_bars = [] if refresh else (prev_daily["bars"] if prev_daily else [])
    old_intraday_bars = [] if refresh else (prev_intraday["bars"] if prev_intraday else [])

    mode = "initial" if previous is None else "incremental"
    daily_start = _daily_start(old_daily_bars, now)
    intraday_start = _intraday_start(old_intraday_bars, now)
    end = now + timedelta(days=1)
    provider = provider or YahooPriceProvider()
    errors = []
    incoming_daily = []
    incoming_intraday = []

    # --- Daily fetch ---
    daily_error = None
    try:
        incoming_daily = normalize_daily(
            provider.fetch_daily(symbol, daily_start, end)
        )
    except (PriceProviderError, PriceDataError) as exc:
        daily_error = exc
        errors.append(_error(
            exc.code,
            "Daily price retrieval failed",
            getattr(exc, "retryable", False),
        ))

    # --- Corporate action detection ---
    reconcile_reason = None
    if old_daily_bars and incoming_daily and has_new_corporate_action(old_daily_bars, incoming_daily):
        try:
            daily_start = _five_year_start(now)
            incoming_daily = normalize_daily(
                provider.fetch_daily(symbol, daily_start, end)
            )
            mode = "full_reconcile"
            reconcile_reason = "corporate_action"
            old_daily_bars = []
            daily_error = None
        except (PriceProviderError, PriceDataError) as exc:
            errors.append(_error(
                exc.code,
                "Daily reconciliation failed",
                getattr(exc, "retryable", False),
            ))
            incoming_daily = []

    # --- Intraday fetch ---
    intraday_error = None
    try:
        incoming_intraday = normalize_intraday(
            provider.fetch_intraday(symbol, intraday_start, end)
        )
    except (PriceProviderError, PriceDataError) as exc:
        intraday_error = exc
        errors.append(_error(
            exc.code,
            "Intraday price retrieval failed",
            getattr(exc, "retryable", False),
        ))

    # --- Build daily series (merge or fall back) ---
    if incoming_daily:
        daily_bars = merge_bars(old_daily_bars, incoming_daily, "date")
        daily_series = _series_result(daily_bars, "ok", now.isoformat())
    elif daily_error and prev_daily:
        # Fetch failed — preserve previous data (P1#1 safety net)
        daily_series = dict(prev_daily)
    elif old_daily_bars:
        # No new data but nothing errored — keep existing with prior freshness
        daily_series = dict(prev_daily) if prev_daily else _series_result(old_daily_bars, "ok", "")
    else:
        daily_series = _empty_series("not_available", "")

    # --- Build intraday series (merge or fall back) ---
    if incoming_intraday:
        intraday_bars = merge_bars(old_intraday_bars, incoming_intraday, "timestamp")
        cutoff = now - timedelta(days=60)
        intraday_bars = [
            bar for bar in intraday_bars
            if datetime.fromisoformat(bar["timestamp"]) >= cutoff
        ]
        intraday_series = _intraday_series_result(intraday_bars, "ok", now.isoformat())
    elif intraday_error and prev_intraday:
        # Fetch failed — preserve previous data (P1#1 safety net)
        intraday_series = dict(prev_intraday)
    elif old_intraday_bars:
        cutoff = now - timedelta(days=60)
        kept = [
            bar for bar in old_intraday_bars
            if datetime.fromisoformat(bar["timestamp"]) >= cutoff
        ]
        intraday_series = _intraday_series_result(kept, "ok", prev_intraday["fetched_at"] if prev_intraday else "")
    else:
        intraday_series = _empty_series("not_available", "")

    payload = _build_payload(
        normalized, symbol, now, mode, daily_start, intraday_start,
        daily_series, intraday_series, errors, reconcile_reason, minimum_daily_rows,
    )

    # Save only if we fetched new data for at least one series and didn't lose data
    daily_fetched_new = bool(incoming_daily)
    intraday_fetched_new = bool(incoming_intraday)
    daily_ok = daily_series["status"] == "ok" and daily_series["bars"]
    intraday_ok = intraday_series["status"] == "ok" and intraday_series["bars"]
    has_data = daily_ok or intraday_ok

    if payload["status"] == "failed":
        return payload
    if daily_fetched_new or intraday_fetched_new:
        if has_data:
            store.save(normalized, payload)
    elif previous is not None:
        store.save(normalized, payload)
    return payload


import argparse
import json
import sys


def _parser():
    parser = argparse.ArgumentParser(prog="stock-price-fetch")
    parser.add_argument("ticker")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    result = fetch_stock_price(
        args.ticker,
        args.data_dir,
        refresh=args.refresh,
    )
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    sys.stdout.write("\n")
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
