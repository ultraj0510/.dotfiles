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


def _failed_result(raw_ticker, now, code, message):
    return {
        "schema_version": "1.0",
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
            "daily": [],
            "intraday_1h": [],
        },
        "sources": [],
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


def _build_summary(daily, intraday, minimum_daily_rows):
    return {
        "daily_rows": len(daily),
        "intraday_rows": len(intraday),
        "daily_first_date": daily[0]["date"] if daily else None,
        "daily_last_date": daily[-1]["date"] if daily else None,
        "intraday_first_timestamp": intraday[0]["timestamp"] if intraday else None,
        "intraday_last_timestamp": intraday[-1]["timestamp"] if intraday else None,
        "usable": len(daily) >= minimum_daily_rows,
    }


def _daily_start(existing, now):
    if not existing:
        return _five_year_start(now)
    last = datetime.fromisoformat(existing[-1]["date"]).replace(tzinfo=JST)
    return last - timedelta(days=10)


def _intraday_start(existing, now):
    if not existing:
        return now - timedelta(days=60)
    return datetime.fromisoformat(existing[-1]["timestamp"]) - timedelta(hours=2)


def _build_payload(
    ticker,
    symbol,
    now,
    mode,
    daily_start,
    intraday_start,
    daily,
    intraday,
    errors,
    reconcile_reason,
    minimum_daily_rows,
):
    status = "success" if not errors else "partial"
    summary = _build_summary(daily, intraday, minimum_daily_rows)
    if not daily and not intraday:
        status = "failed"
    return {
        "schema_version": "1.0",
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
            "daily": daily,
            "intraday_1h": intraday,
        },
        "sources": [{
            "provider": "yahoo_finance",
            "symbol": symbol,
            "fetched_at": now.isoformat(),
        }],
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
    previous = None if refresh else store.load(normalized)
    old_daily = previous["data"]["daily"] if previous else []
    old_intraday = previous["data"]["intraday_1h"] if previous else []
    mode = "initial" if previous is None else "incremental"
    daily_start = _daily_start(old_daily, now)
    intraday_start = _intraday_start(old_intraday, now)
    end = now + timedelta(days=1)
    provider = provider or YahooPriceProvider()
    errors = []
    incoming_daily = []
    incoming_intraday = []

    try:
        incoming_daily = normalize_daily(
            provider.fetch_daily(symbol, daily_start, end)
        )
    except (PriceProviderError, PriceDataError) as exc:
        errors.append(_error(
            exc.code,
            "Daily price retrieval failed",
            getattr(exc, "retryable", False),
        ))

    reconcile_reason = None
    if old_daily and incoming_daily and has_new_corporate_action(old_daily, incoming_daily):
        try:
            daily_start = _five_year_start(now)
            incoming_daily = normalize_daily(
                provider.fetch_daily(symbol, daily_start, end)
            )
            mode = "full_reconcile"
            reconcile_reason = "corporate_action"
            old_daily = []
        except (PriceProviderError, PriceDataError) as exc:
            errors.append(_error(
                exc.code,
                "Daily reconciliation failed",
                getattr(exc, "retryable", False),
            ))
            incoming_daily = []

    try:
        incoming_intraday = normalize_intraday(
            provider.fetch_intraday(symbol, intraday_start, end)
        )
    except (PriceProviderError, PriceDataError) as exc:
        errors.append(_error(
            exc.code,
            "Intraday price retrieval failed",
            getattr(exc, "retryable", False),
        ))

    daily = merge_bars(old_daily, incoming_daily, "date")
    intraday = merge_bars(old_intraday, incoming_intraday, "timestamp")
    cutoff = now - timedelta(days=60)
    intraday = [
        bar for bar in intraday
        if datetime.fromisoformat(bar["timestamp"]) >= cutoff
    ]

    payload = _build_payload(
        normalized,
        symbol,
        now,
        mode,
        daily_start,
        intraday_start,
        daily,
        intraday,
        errors,
        reconcile_reason,
        minimum_daily_rows,
    )
    received_new_data = bool(incoming_daily or incoming_intraday)
    if payload["status"] == "failed":
        return payload
    if received_new_data:
        store.save(normalized, payload)
    return payload
