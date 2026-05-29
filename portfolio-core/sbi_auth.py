"""SBI session cookie validation via Playwright.

Extracted from Claude版 portfolio-auth/auth_sbi.py.
"""

import json

# SBI portfolio page (requires authentication).
# Use site1.sbisec.co.jp directly — JSESSIONID is hostOnly for this domain
# and won't be sent to www.sbisec.co.jp. SBI serves authenticated pages from site1.
SBI_CHECK_URL = "https://site1.sbisec.co.jp/ETGate/?_ControlID=WPLETpfR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETpfR001Control&OutSide=on&getFlg=on&_scpr=intpr=hn_trade"
CRITICAL_KEYS = ["JSESSIONID", "__lt__sid", "__lt__cid", "AWSALBCORS"]


def parse_cookies(raw: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            tokens[key.strip()] = value.strip()
    return tokens


def parse_cookie_input(raw: str) -> dict[str, str]:
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("[") or raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return parse_cookies(raw)
        if isinstance(data, dict):
            data = data.get("tokens", data)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        if isinstance(data, list):
            result: dict[str, str] = {}
            for obj in data:
                if isinstance(obj, dict) and obj.get("name") and obj.get("value") is not None:
                    result[str(obj["name"])] = str(obj["value"])
            return result
    return parse_cookies(raw)


def reconstruct_header(tokens: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in tokens.items())


def missing_critical_keys(tokens: dict[str, str]) -> list[str]:
    return [key for key in CRITICAL_KEYS if not tokens.get(key)]


def cookie_objects_from_raw(raw: str) -> list[dict]:
    """Convert raw cookie data to Playwright-compatible objects."""
    try:
        data = json.loads(raw) if raw.strip().startswith("[") else None
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        cookie_list = []
        for obj in data:
            c = {
                "name": obj["name"],
                "value": obj["value"],
                "domain": obj.get("domain", ".sbisec.co.jp"),
                "path": obj.get("path", "/"),
            }
            if obj.get("secure"):
                c["secure"] = True
            if obj.get("httpOnly"):
                c["httpOnly"] = True
            st = obj.get("sameSite")
            if st and st not in ("unspecified", None):
                st = st.replace("_", "-").lower()
                st_map = {"no-restriction": "None", "lax": "Lax", "strict": "Strict", "none": "None"}
                c["sameSite"] = st_map.get(st, "Lax")
            cookie_list.append(c)
        return cookie_list
    return [
        {"name": name, "value": value, "domain": ".sbisec.co.jp", "path": "/"}
        for name, value in parse_cookie_input(raw).items()
    ]


def classify_sbi_html(html: str, url: str = "") -> str | None:
    """Classify SBI page HTML. Returns OK/EXPIRED/MAINTENANCE/None."""
    lowered_url = url.lower()
    lowered_html = html.lower()
    login_markers = [
        "login-entry",
        "ログインページです",
        "ログインしてください",
        "ユーザーネーム",
        "name=\"user_id\"",
        "name=\"password\"",
    ]
    if "login" in lowered_url or any(marker in lowered_html or marker in html for marker in login_markers):
        return "EXPIRED"
    maintenance_markers = ["メンテナンス中", "ただいまメンテナンス"]
    if "maintenance" in lowered_url or any(marker in lowered_html or marker in html for marker in maintenance_markers):
        return "MAINTENANCE"
    success_markers = [
        "WPLETpfR001Control",
        "保有証券",
        "ポートフォリオ",
        "株式（現物",
        "株式(現物",
        "信用建玉",
    ]
    if any(marker in html or marker in url for marker in success_markers):
        return "OK"
    return None


def validate(cookie_json: str) -> tuple[str, str | None]:
    """Validate SBI session via Playwright. Returns (status, error_or_None)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ("ERROR", "Playwright not installed. Run: pip install playwright && playwright install chromium")

    tokens = parse_cookie_input(cookie_json)
    missing = missing_critical_keys(tokens)
    if missing:
        return ("ERROR", f"Missing critical cookies: {', '.join(missing)}")
    cookie_list = cookie_objects_from_raw(cookie_json)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                locale="ja-JP", timezone_id="Asia/Tokyo",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800})
            context.add_cookies(cookie_list)
            page = context.new_page()
            page.goto(SBI_CHECK_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            url = page.url
            html = page.content()
            browser.close()

            status = classify_sbi_html(html, url)
            if status:
                return (status, None)
            return ("ERROR", f"Cannot determine auth state: {url[:120]}")
    except Exception as e:
        return ("ERROR", str(e))
