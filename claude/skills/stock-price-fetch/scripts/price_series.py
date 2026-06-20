from zoneinfo import ZoneInfo

import pandas as pd


JST = ZoneInfo("Asia/Tokyo")

DAILY_COLUMNS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adjusted_close",
    "Volume": "volume",
    "Dividends": "dividend",
    "Stock Splits": "stock_split",
}

INTRADAY_COLUMNS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adjusted_close",
    "Volume": "volume",
}


class PriceDataError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _number(value, integer=False):
    if pd.isna(value):
        return None
    number = float(value)
    return int(number) if integer else number


def _validate_bar(bar):
    prices = [bar[name] for name in ("open", "high", "low", "close")]
    if any(value is None or value <= 0 for value in prices):
        raise PriceDataError("invalid_price", "OHLC must be positive")
    if bar["high"] < max(bar["open"], bar["low"], bar["close"]):
        raise PriceDataError("invalid_ohlc", "high is below another price")
    if bar["low"] > min(bar["open"], bar["high"], bar["close"]):
        raise PriceDataError("invalid_ohlc", "low is above another price")
    if bar["volume"] is not None and bar["volume"] < 0:
        raise PriceDataError("invalid_volume", "volume must not be negative")


def _normalize(frame, columns, key_builder):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise PriceDataError("missing_columns", ",".join(sorted(missing)))
    bars = []
    previous_key = None
    for timestamp, row in frame.sort_index().iterrows():
        bar = {key_builder(timestamp)[0]: key_builder(timestamp)[1]}
        for source, target in columns.items():
            bar[target] = _number(row[source], integer=target == "volume")
        _validate_bar(bar)
        key = next(iter(bar.values()))
        if previous_key is not None and key <= previous_key:
            raise PriceDataError("non_increasing_time", str(key))
        previous_key = key
        bars.append(bar)
    return bars


def normalize_daily(frame):
    return _normalize(
        frame,
        DAILY_COLUMNS,
        lambda value: ("date", pd.Timestamp(value).date().isoformat()),
    )


def normalize_intraday(frame):
    def key(value):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise PriceDataError("timezone_missing", str(value))
        return "timestamp", timestamp.tz_convert(JST).isoformat()
    return _normalize(frame, INTRADAY_COLUMNS, key)


def merge_bars(existing, incoming, key):
    merged = {bar[key]: bar for bar in existing}
    merged.update({bar[key]: bar for bar in incoming})
    return [merged[value] for value in sorted(merged)]


def has_new_corporate_action(existing, incoming):
    old = {
        bar["date"]: (bar.get("dividend") or 0.0, bar.get("stock_split") or 0.0)
        for bar in existing
    }
    for bar in incoming:
        current = (bar.get("dividend") or 0.0, bar.get("stock_split") or 0.0)
        if current != (0.0, 0.0) and old.get(bar["date"], (0.0, 0.0)) != current:
            return True
    return False
