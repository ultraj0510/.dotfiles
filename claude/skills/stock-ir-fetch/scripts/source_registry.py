"""Persist and validate approved IR source definitions."""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


class SourceRegistry:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, ticker: str) -> Path:
        return self.root / ticker / "raw" / "stock-ir-fetch" / "source.json"

    def load(self, ticker: str) -> dict | None:
        path = self.path_for(ticker)
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_nonfinite,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        if not _validate_source(payload, ticker):
            return None
        return payload

    def approve(self, ticker: str, candidate: dict, approved_at: datetime) -> dict:
        parsed = urlparse(candidate["ir_top_url"])
        domain = parsed.hostname or ""
        source = {
            "schema_version": "1.0",
            "ticker": ticker,
            "company_name": candidate.get("company_name", ""),
            "company_site_url": candidate.get("company_site_url", ""),
            "ir_top_url": candidate["ir_top_url"],
            "document_index_url": candidate.get("document_index_url", candidate["ir_top_url"]),
            "approved_domain": candidate.get("approved_domain", domain),
            "approved_at": approved_at.isoformat(),
            "approval_method": "user",
            "last_verified_at": approved_at.isoformat(),
            "last_successful_sync_at": None,
        }
        self._save(ticker, source)
        return source

    def update_sync_times(self, ticker: str, verified_at: datetime, successful_at: datetime | None) -> dict:
        source = self.load(ticker)
        if not source:
            raise ValueError("No approved source for ticker")
        source["last_verified_at"] = verified_at.isoformat()
        source["last_successful_sync_at"] = successful_at.isoformat() if successful_at else None
        self._save(ticker, source)
        return source

    def _save(self, ticker: str, payload: dict) -> Path:
        path = self.path_for(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                suffix=".tmp", delete=False,
            ) as tmp:
                temporary_path = Path(tmp.name)
                json.dump(payload, tmp, ensure_ascii=False, indent=2, allow_nan=False)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
            temporary_path.chmod(0o600)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
        return path


def _reject_nonfinite(value):
    raise ValueError(f"Non-finite number in JSON: {value}")


def _is_url_on_domain(url: str, domain: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False
    from safe_http import registrable_domain
    return registrable_domain(parsed.hostname or "") == domain


def _validate_source(payload, ticker: str) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schema_version") != "1.0":
        return False
    if payload.get("ticker") != ticker:
        return False
    domain = payload.get("approved_domain")
    if not domain or not isinstance(domain, str):
        return False
    for key in ("company_site_url", "ir_top_url", "document_index_url"):
        if not _is_url_on_domain(payload.get(key, ""), domain):
            return False
    if payload.get("approval_method") != "user":
        return False
    for key in ("approved_at", "last_verified_at"):
        val = payload.get(key)
        if not isinstance(val, str):
            return False
        try:
            datetime.fromisoformat(val)
        except ValueError:
            return False
    sync_at = payload.get("last_successful_sync_at")
    if sync_at is not None:
        if not isinstance(sync_at, str):
            return False
        try:
            datetime.fromisoformat(sync_at)
        except ValueError:
            return False
    return True
