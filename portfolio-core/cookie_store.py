"""Unified cookie store for SBI portfolio auth/fetch.

Canonical storage: ~/.config/sbi-portfolio/tokens.json

Read priority:
  1. SBI_COOKIE environment variable
  2. ~/.config/sbi-portfolio/tokens.json (canonical)
  3. Legacy paths (one-time migration): .claude/.cookie → .claude/.tokens.json
     → .agents/.cookie → .agents/.tokens.json
"""

import json
import os
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

CRITICAL_KEYS = {"JSESSIONID", "AWSALB", "AWSALBCORS"}


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
            return "; ".join(f"{c['name']}={c['value']}" for c in data)
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
                return raw  # plain cookie string
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
    return None


def read_cookie_objects() -> list[dict]:
    """Read SBI cookies as Playwright-compatible objects with full attributes."""
    cookie_str = os.environ.get("SBI_COOKIE", "").strip()
    if not cookie_str:
        if CANONICAL_FILE.exists():
            cookie_str = CANONICAL_FILE.read_text().strip()
        else:
            for legacy in LEGACY_PATHS:
                if legacy.exists():
                    cookie_str = legacy.read_text().strip()
                    break
    if not cookie_str:
        return []
    return _json_to_cookie_objects(cookie_str)


def _json_to_cookie_objects(raw: str) -> list[dict]:
    """Convert JSON array cookie data to Playwright-compatible objects."""
    if not raw.startswith("["):
        return []
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


def save_cookie(cookie_str: str):
    """Validate and save cookie to canonical location.

    Accepts JSON array (Cookie-Editor export), JSON object with tokens dict,
    or plain cookie string. Validates that critical session keys are present.
    """
    # Parse to JSON array format for canonical storage
    data = _normalize_cookie_data(cookie_str)
    if not data:
        raise ValueError("Could not parse cookie data")

    names = {c["name"] for c in data}
    missing = CRITICAL_KEYS - names
    if missing:
        raise ValueError(f"Missing critical cookies: {missing}")

    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    CANONICAL_DIR.chmod(0o700)
    CANONICAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    CANONICAL_FILE.chmod(0o600)


def _normalize_cookie_data(raw: str) -> list[dict] | None:
    """Convert any supported cookie format to JSON array."""
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
    # Plain cookie string
    pairs = []
    for pair in raw.split("; "):
        if "=" in pair:
            n, v = pair.split("=", 1)
            pairs.append({"name": n.strip(), "value": v.strip(), "domain": ".sbisec.co.jp", "path": "/"})
    return pairs if pairs else None


def migrate_legacy() -> bool:
    """One-time migration: copy best available legacy cookie to canonical."""
    if CANONICAL_FILE.exists():
        return False  # already migrated

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
