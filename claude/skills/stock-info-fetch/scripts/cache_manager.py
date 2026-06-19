"""Daily cache manager for stock-info-fetch.

Cache key: ticker code + JST date. Atomic writes via temp file + rename.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".claude" / "cache" / "stock-info-fetch"
JST = timezone(timedelta(hours=9))


class CacheManager:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.chmod(0o700)

    def _cache_path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker}.json"

    def _today(self) -> str:
        return datetime.now(JST).strftime("%Y-%m-%d")

    def get(self, ticker: str, refresh: bool = False) -> dict | None:
        if refresh:
            return None
        path = self._cache_path(ticker)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        cached_date = data.get("cache", {}).get("date", "")
        if cached_date != self._today():
            return None
        data["cache"]["hit"] = True
        return data

    def save(self, ticker: str, data: dict) -> None:
        data["cache"]["hit"] = False
        data["cache"]["date"] = self._today()
        path = self._cache_path(ticker)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.chmod(0o600)
        os.replace(tmp_path, path)
