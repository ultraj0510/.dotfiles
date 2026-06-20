"""Daily cache manager for stock-info-fetch.

Cache key: ticker code + JST date. Atomic writes via temp file + rename.
"""
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".claude" / "cache" / "stock-info-fetch"
JST = timezone(timedelta(hours=9))

VALID_STATUSES = {"ok", "not_available", "error"}
EXPECTED_SECTIONS = {
    "price", "company_profile", "company_scores",
    "performance", "news", "disclosures", "stock_reports",
}


def _is_valid_cache(data: object, ticker: str, today: str) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("schema_version") != "1.0" or data.get("ticker") != ticker:
        return False
    cache = data.get("cache")
    if not isinstance(cache, dict) or cache.get("date") != today:
        return False
    sections = data.get("sections")
    if not isinstance(sections, dict) or set(sections) != EXPECTED_SECTIONS:
        return False
    for section in sections.values():
        if not isinstance(section, dict):
            return False
        if section.get("status") not in VALID_STATUSES:
            return False
        if "data" not in section:
            return False
        source = section.get("source")
        if not isinstance(source, dict):
            return False
        if not isinstance(source.get("url"), str):
            return False
    return True


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
        except (json.JSONDecodeError, UnicodeDecodeError, Exception):
            return None
        if not _is_valid_cache(data, ticker, self._today()):
            return None
        data["cache"]["hit"] = True
        return data

    def save(self, ticker: str, data: dict) -> None:
        data["cache"]["hit"] = False
        data["cache"]["date"] = self._today()
        path = self._cache_path(ticker)
        with tempfile.NamedTemporaryFile(
            dir=self.cache_dir, delete=False, suffix=".tmp", mode="w", encoding="utf-8"
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp.name, 0o600)
        os.replace(tmp.name, path)
