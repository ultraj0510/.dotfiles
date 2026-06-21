import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

_DAILY_REQUIRED_KEYS = {"date", "open", "high", "low", "close", "volume"}
_INTRADAY_REQUIRED_KEYS = {"timestamp", "open", "high", "low", "close", "volume"}
_PRICE_KEYS = {"open", "high", "low", "close"}


class PriceStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, ticker: str) -> Path:
        return self.root / ticker / "raw" / "stock-price-fetch" / "prices.json"

    def load(self, ticker: str) -> dict | None:
        path = self.path_for(ticker)
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_nonfinite_numbers,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        if payload.get("schema_version") != "1.1":
            return None
        if payload.get("ticker") != ticker:
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        daily = data.get("daily")
        intraday = data.get("intraday_1h")
        if not isinstance(daily, dict) or not isinstance(intraday, dict):
            return None
        for series, required_keys, key_name in [
            (daily, _DAILY_REQUIRED_KEYS, "date"),
            (intraday, _INTRADAY_REQUIRED_KEYS, "timestamp"),
        ]:
            if not _validate_series_structure(series, required_keys, key_name):
                return None
        return payload

    def save(self, ticker: str, payload: dict) -> Path:
        path = self.path_for(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, ensure_ascii=False, indent=2, allow_nan=False)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o600)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
        return path


def _reject_nonfinite_numbers(value):
    raise ValueError(f"Non-finite number in JSON: {value}")


def _validate_series_structure(series: dict, required_keys: set, key_name: str) -> bool:
    bars = series.get("bars")
    if not isinstance(bars, list):
        return False
    status = series.get("status")
    if status not in ("ok", "not_available", "error"):
        return False
    # fetched_at must be valid ISO datetime
    fetched_at = series.get("fetched_at")
    if not isinstance(fetched_at, str):
        return False
    if not _is_iso_datetime(fetched_at):
        return False
    # data_as_of: None if empty, must match last bar's key if non-empty
    data_as_of = series.get("data_as_of")
    if bars:
        if not isinstance(data_as_of, str):
            return False
        if data_as_of != bars[-1].get(key_name):
            return False
    elif data_as_of is not None:
        return False
    # Validate each bar
    previous_key = None
    for bar in bars:
        if not isinstance(bar, dict):
            return False
        if not required_keys.issubset(bar.keys()):
            return False
        key = bar.get(key_name)
        if not isinstance(key, str):
            return False
        if key_name == "date":
            if not _is_iso_date(key):
                return False
        elif key_name == "timestamp":
            if not _is_iso_datetime(key):
                return False
            try:
                if datetime.fromisoformat(key).tzinfo is None:
                    return False
            except ValueError:
                return False
        # Validate numeric values: must be finite numbers
        for price_key in _PRICE_KEYS:
            val = bar.get(price_key)
            if val is None or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
                return False
        # OHLC consistency
        if bar["high"] < max(bar["open"], bar["low"], bar["close"]):
            return False
        if bar["low"] > min(bar["open"], bar["high"], bar["close"]):
            return False
        # Volume: non-negative integer
        vol = bar.get("volume")
        if vol is not None:
            if not isinstance(vol, (int, float)) or not math.isfinite(vol) or vol < 0:
                return False
            # Must be integer-valued (no fractional shares)
            if isinstance(vol, float) and vol != int(vol):
                return False
        # Sort order
        if previous_key is not None and key <= previous_key:
            return False
        previous_key = key
    return True


def _is_iso_date(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _is_iso_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False
