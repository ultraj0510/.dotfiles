"""Immutable version storage for IR documents."""
import hashlib
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode


def normalize_document_url(url):
    """Remove tracking query params and fragments for stable ID generation."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                "ref", "source", "fbclid", "gclid", "_ga", "_gl"}
    cleaned = {k: v for k, v in params.items() if k.lower() not in tracking}
    new_query = urlencode(cleaned, doseq=True)
    new = parsed._replace(query=new_query, fragment="")
    if new_query:
        return new.geturl()
    return new.geturl().rstrip("?")


def document_id(url, published_at):
    h = hashlib.sha256(f"{normalize_document_url(url)}\n{published_at}".encode())
    return h.hexdigest()[:24]


class DocumentStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def doc_path(self, ticker, doc_id):
        return self.root / ticker / "raw" / "stock-ir-fetch" / "documents" / doc_id

    def manifest_path(self, ticker):
        return self.root / ticker / "raw" / "stock-ir-fetch" / "manifest.json"

    def load_manifest(self, ticker):
        path = self.manifest_path(ticker)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"),
                                 parse_constant=_reject_nonfinite)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        if not _validate_manifest(payload, ticker):
            return None
        return payload

    def save_version(self, ticker, entry, fetched, extraction, now):
        doc_id = document_id(entry["url"], entry["published_at"])
        doc_dir = self.doc_path(ticker, doc_id)
        version_dir = doc_dir / "versions" / fetched["sha256"]
        is_new_document = not doc_dir.exists()
        is_new_version = not version_dir.exists()

        if is_new_version:
            version_dir.mkdir(parents=True, exist_ok=True)

            # Save original
            ext = fetched["extension"]
            orig_path = version_dir / f"original.{ext}"
            _atomic_write(orig_path, fetched["body"], binary=True)

            # Save extracted text
            text_path = version_dir / "extracted.txt"
            _atomic_write(text_path, extraction.get("text", "").encode("utf-8"), binary=True)

            # Save extraction metadata
            ext_meta = {
                "method": extraction.get("method", ""),
                "page_count": extraction.get("page_count"),
                "quality_warnings": extraction.get("quality_warnings", []),
                "error": extraction.get("error"),
                "extracted_at": now.isoformat(),
            }
            meta_path = version_dir / "extraction.json"
            _atomic_write(meta_path, json.dumps(ext_meta, ensure_ascii=False, indent=2).encode("utf-8"), binary=True)

            # Save/update document metadata
            doc_meta = {
                "document_id": doc_id,
                "title": entry.get("title", ""),
                "published_at": entry.get("published_at", ""),
                "url": entry["url"],
                "latest_sha256": fetched["sha256"],
                "latest_extension": ext,
                "version_count": 1,
            }
            existing = doc_dir / "metadata.json"
            if existing.exists():
                try:
                    prev_meta = json.loads(existing.read_text())
                    doc_meta["version_count"] = prev_meta.get("version_count", 0) + 1
                except Exception:
                    pass
            _atomic_write(existing, json.dumps(doc_meta, ensure_ascii=False, indent=2).encode("utf-8"), binary=True)

        return {
            "document_id": doc_id,
            "sha256": fetched["sha256"],
            "is_new_document": is_new_document,
            "is_new_version": is_new_version,
            "local_path": str(version_dir.relative_to(self.root)),
        }, is_new_version

    def save_manifest(self, ticker, manifest):
        path = self.manifest_path(ticker)
        _atomic_write(path, json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"), binary=True)
        return path


def _atomic_write(path, data, binary=False):
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    parent.chmod(0o700)
    mode = "wb" if binary else "w"
    encoding = None if binary else "utf-8"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode=mode, encoding=encoding,
                                         dir=parent, suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        tmp_path.chmod(0o600)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _reject_nonfinite(value):
    raise ValueError(f"Non-finite number: {value}")


def _validate_manifest(payload, ticker):
    if not isinstance(payload, dict):
        return False
    if payload.get("schema_version") != "1.1":
        return False
    if payload.get("ticker") != ticker:
        return False
    # as_of must be timezone-aware ISO datetime
    try:
        dt = datetime.fromisoformat(payload.get("as_of", ""))
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        return False
    # status must be valid
    if payload.get("status") not in ("success", "partial", "failed", "unsupported"):
        return False
    # sync must be a dict with valid mode and new schema 1.1 fields
    sync = payload.get("sync")
    if not isinstance(sync, dict):
        return False
    if sync.get("mode") not in ("none", "initial", "incremental", "full_reconcile"):
        return False
    ws = sync.get("window_start")
    we = sync.get("window_end")
    if not isinstance(ws, (str, type(None))):
        return False
    if not isinstance(we, (str, type(None))):
        return False
    if ws and we:
        try:
            wsd = date.fromisoformat(ws)
            wed = date.fromisoformat(we)
        except (ValueError, TypeError):
            return False
        if wsd > wed:
            return False
    # start_urls must be list of HTTPS strings
    start_urls = sync.get("start_urls")
    if not isinstance(start_urls, list):
        return False
    for u in start_urls:
        if not isinstance(u, str) or not u.startswith("https://"):
            return False
    # dynamic_pages must be list of strings
    dynamic_pages = sync.get("dynamic_pages")
    if not isinstance(dynamic_pages, list):
        return False
    for u in dynamic_pages:
        if not isinstance(u, str):
            return False
    # summary must be a dict with correct types
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return False
    if not isinstance(summary.get("usable"), bool):
        return False
    if not isinstance(summary.get("coverage_complete"), bool):
        return False
    for key in ("discovered", "new_documents", "new_versions", "unchanged",
                "no_longer_listed", "fetch_errors", "extraction_errors",
                "prohibited_documents", "dynamic_pages"):
        val = summary.get(key)
        if not isinstance(val, int) or isinstance(val, bool):
            return False
        if val < 0:
            return False
    # latest_published_at must be valid date string or None
    lpa = summary.get("latest_published_at")
    if lpa is not None:
        if not isinstance(lpa, str):
            return False
        try:
            date.fromisoformat(lpa)
        except (ValueError, TypeError):
            return False
    # errors must be list of dicts with section/code/message
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return False
    for e in errors:
        if not isinstance(e, dict):
            return False
        if not isinstance(e.get("section"), str):
            return False
        if not isinstance(e.get("code"), str):
            return False
        if not isinstance(e.get("message"), str):
            return False
    # documents must be list of dicts with 24-char hex doc_id and 64-char hex sha256
    docs = payload.get("documents")
    if not isinstance(docs, list):
        return False
    doc_ids = set()
    for doc in docs:
        if not isinstance(doc, dict):
            return False
        did = doc.get("document_id")
        sha = doc.get("sha256")
        if not isinstance(did, str) or not isinstance(sha, str):
            return False
        if len(did) != 24 or not all(c in "0123456789abcdef" for c in did):
            return False
        if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
            return False
        if did in doc_ids:
            return False
        doc_ids.add(did)
    return True
