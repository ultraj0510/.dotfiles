import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

_DAILY_REQUIRED_KEYS = {"date", "open", "high", "low", "close", "volume"}
_INTRADAY_REQUIRED_KEYS = {"timestamp", "open", "high", "low", "close", "volume"}


class PriceStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, ticker: str) -> Path:
        return self.root / ticker / "raw" / "stock-price-fetch" / "prices.json"

    def load(self, ticker: str) -> dict | None:
        path = self.path_for(ticker)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
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
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2, allow_nan=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        return path


def _validate_series_structure(series: dict, required_keys: set, key_name: str) -> bool:
    bars = series.get("bars")
    if not isinstance(bars, list):
        return False
    status = series.get("status")
    if status not in ("ok", "not_available", "error"):
        return False
    if not isinstance(series.get("fetched_at"), str):
        return False
    if not bars:
        return True
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
            try:
                datetime.fromisoformat(key)
            except ValueError:
                return False
        elif key_name == "timestamp":
            try:
                dt = datetime.fromisoformat(key)
                if dt.tzinfo is None:
                    return False
            except ValueError:
                return False
        if previous_key is not None and key <= previous_key:
            return False
        previous_key = key
    return True
