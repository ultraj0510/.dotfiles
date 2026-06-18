"""Unified cookie store for SBI portfolio auth/fetch.

Canonical storage: ~/.config/sbi-portfolio/tokens.json

Read priority:
  1. SBI_COOKIE environment variable
  2. ~/.config/sbi-portfolio/tokens.json (canonical)
  3. Legacy paths (one-time migration): .claude/.cookie → .claude/.tokens.json
    → .agents/.cookie → .agents/.tokens.json
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

CANONICAL_DIR = Path.home() / ".config" / "sbi-portfolio"
CANONICAL_FILE = CANONICAL_DIR / "tokens.json"

LEGACY_PATHS = [
    Path.home() / ".claude" / "skills" / "portfolio-auth" / ".cookie",
    Path.home() / ".dotfiles" / "claude" / "skills" / "portfolio-auth" / ".cookie",
    Path.home() / ".claude" / "skills" / "portfolio-auth" / ".tokens.json",
    Path.home() / ".dotfiles" / "claude" / "skills" / "portfolio-auth" / ".tokens.json",
    Path.home() / ".agents" / "skills" / "portfolio-auth" / ".cookie",
    Path.home() / ".agents" / "skills" / "portfolio-auth" / ".tokens.json",
]

# Single source of truth for critical SBI session cookie keys.
CRITICAL_KEYS = {"JSESSIONID", "__lt__sid", "__lt__cid", "AWSALBCORS"}


def cookie_fingerprint(cookies: list[dict]) -> str:
    """Return a 12-char non-secret fingerprint from critical cookie values."""
    parts = []
    for name in sorted(CRITICAL_KEYS):
        value = next((str(c.get("value", "")) for c in cookies if c.get("name") == name), "")
        parts.append(f"{name}={value}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def read_cookie() -> str | None:
    """Read SBI cookie string. Env var takes precedence over file."""
    env_val = os.environ.get("SBI_COOKIE", "").strip()
    if env_val:
        return env_val
    return _read_from_file()


def _read_from_file() -> str | None:
    if CANONICAL_FILE.exists():
        try:
            data = json.loads(CANONICAL_FILE.read_text())
            cookies = _extract_cookies(data)
            if cookies:
                return "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        except (json.JSONDecodeError, KeyError):
            pass
    for legacy in LEGACY_PATHS:
        if legacy.exists():
            try:
                raw = legacy.read_text().strip()
                if raw.startswith("["):
                    data = json.loads(raw)
                    return "; ".join(f"{c['name']}={c['value']}" for c in data)
                if raw.startswith("{"):
                    data = json.loads(raw)
                    tokens = data.get("tokens", data)
                    if isinstance(tokens, dict):
                        return "; ".join(f"{k}={v}" for k, v in tokens.items())
                return raw
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
    return None


def _extract_cookies(data) -> list[dict]:
    """Extract cookie list from canonical data, supporting legacy array and new metadata format."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("cookies", [])
    return []


def read_cookie_objects() -> list[dict]:
    """Read SBI cookies as Playwright-compatible objects with full attributes."""
    cookie_str = os.environ.get("SBI_COOKIE", "").strip()
    if cookie_str:
        return _normalize_cookie_data(cookie_str)

    if CANONICAL_FILE.exists():
        try:
            data = json.loads(CANONICAL_FILE.read_text())
            cookies = _extract_cookies(data)
            if cookies:
                return _json_to_cookie_objects(json.dumps(cookies))
        except (json.JSONDecodeError, KeyError):
            pass

    for legacy in LEGACY_PATHS:
        if legacy.exists():
            raw = legacy.read_text().strip()
            result = _normalize_cookie_data(raw)
            if result:
                return result
    return []


def _json_to_cookie_objects(raw: str) -> list[dict]:
    """Convert JSON array cookie data to Playwright-compatible objects."""
    if not raw.startswith("["):
        return _normalize_cookie_data(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    cookies = []
    for obj in data:
        c = {"name": obj["name"], "value": obj["value"],
             "domain": obj.get("domain", ".sbisec.co.jp"),
             "path": obj.get("path", "/")}
        if obj.get("secure"):
            c["secure"] = True
        if obj.get("httpOnly"):
            c["httpOnly"] = True
        st = obj.get("sameSite")
        if st and st not in ("unspecified", None):
            st = st.replace("_", "-").lower()
            st_map = {"no-restriction": "None", "lax": "Lax", "strict": "Strict", "none": "None"}
            c["sameSite"] = st_map.get(st, "Lax")
        cookies.append(c)
    return cookies


def save_cookie(cookie_str: str, source: str = "unknown"):
    """Validate and save cookie to canonical location with metadata.

    Accepts JSON array (Cookie-Editor export), JSON object with tokens dict,
    or plain cookie string. Validates that critical session keys are present.
    """
    cookies = _normalize_cookie_data(cookie_str)
    if not cookies:
        raise ValueError("Could not parse cookie data")

    names = {c["name"] for c in cookies}
    missing = sorted(CRITICAL_KEYS - names)
    if missing:
        raise ValueError(f"Missing critical cookies: {', '.join(missing)}")

    data = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "fingerprint": cookie_fingerprint(cookies),
        "cookies": cookies,
    }

    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    CANONICAL_DIR.chmod(0o700)
    CANONICAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    CANONICAL_FILE.chmod(0o600)


def read_cookie_bundle() -> dict:
    """Return cookie bundle with header, objects, source, fingerprint, saved_at."""
    env_val = os.environ.get("SBI_COOKIE", "").strip()
    if env_val:
        cookies = _normalize_cookie_data(env_val)
        return {
            "cookie_header": "; ".join(f"{c['name']}={c['value']}" for c in cookies) if cookies else "",
            "cookie_objects": cookies,
            "source": "env",
            "fingerprint": cookie_fingerprint(cookies) if cookies else "",
            "saved_at": None,
        }

    if CANONICAL_FILE.exists():
        try:
            data = json.loads(CANONICAL_FILE.read_text())
            cookies = _extract_cookies(data)
            if cookies:
                return {
                    "cookie_header": "; ".join(f"{c['name']}={c['value']}" for c in cookies),
                    "cookie_objects": _json_to_cookie_objects(json.dumps(cookies)),
                    "source": data.get("source", "canonical") if isinstance(data, dict) else "canonical",
                    "fingerprint": data.get("fingerprint", cookie_fingerprint(cookies)) if isinstance(data, dict) else cookie_fingerprint(cookies),
                    "saved_at": data.get("saved_at") if isinstance(data, dict) else None,
                }
        except (json.JSONDecodeError, KeyError):
            pass

    for legacy in LEGACY_PATHS:
        if legacy.exists():
            raw = legacy.read_text().strip()
            cookies = _normalize_cookie_data(raw)
            if cookies:
                return {
                    "cookie_header": "; ".join(f"{c['name']}={c['value']}" for c in cookies),
                    "cookie_objects": cookies,
                    "source": f"legacy:{legacy}",
                    "fingerprint": cookie_fingerprint(cookies),
                    "saved_at": None,
                }

    return {
        "cookie_header": "",
        "cookie_objects": [],
        "source": "none",
        "fingerprint": "",
        "saved_at": None,
    }


def _normalize_cookie_data(raw: str) -> list[dict]:
    """Convert any supported cookie format to normalized dict list."""
    raw = raw.strip()
    if raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
            tokens = obj.get("tokens", obj)
            if isinstance(tokens, dict):
                return [{"name": k, "value": v, "domain": ".sbisec.co.jp", "path": "/"}
                        for k, v in tokens.items()]
        except json.JSONDecodeError:
            pass
    # Plain cookie string — semicolon-separated
    pairs = []
    for pair in raw.split(";"):
        pair = pair.strip()
        if "=" in pair:
            n, v = pair.split("=", 1)
            pairs.append({"name": n.strip(), "value": v.strip(), "domain": ".sbisec.co.jp", "path": "/"})
    return pairs if pairs else []


def migrate_legacy() -> bool:
    """One-time migration: copy best available legacy cookie to canonical."""
    if CANONICAL_FILE.exists():
        return False

    for legacy in LEGACY_PATHS:
        if not legacy.exists():
            continue
        try:
            raw = legacy.read_text().strip()
            if raw.startswith("["):
                data = json.loads(raw)
                names = {c["name"] for c in data}
                if CRITICAL_KEYS.issubset(names):
                    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
                    CANONICAL_DIR.chmod(0o700)
                    CANONICAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                    CANONICAL_FILE.chmod(0o600)
                    return True
            elif raw.startswith("{"):
                obj = json.loads(raw)
                tokens = obj.get("tokens", {})
                if CRITICAL_KEYS.issubset(set(tokens.keys())):
                    data = [{"name": k, "value": v, "domain": ".sbisec.co.jp", "path": "/"}
                            for k, v in tokens.items()]
                    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
                    CANONICAL_DIR.chmod(0o700)
                    CANONICAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                    CANONICAL_FILE.chmod(0o600)
                    return True
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return False
