#!/usr/bin/env python3
"""SBI証券セッションCookieの管理・検証。

Cookieはユーザがブラウザから手動取得し、--save でファイル保存する。
保存先: ~/.claude/skills/portfolio-auth/.cookie

Usage:
  python3 auth_sbi.py           # 保存済みCookieの有効性を検証
  python3 auth_sbi.py --save    # SBI_COOKIE環境変数の値を検証→保存
"""

import json
import os
import sys
from pathlib import Path

# Validate against the portfolio page (requires authentication).
# urllib always gets redirected regardless of cookie validity,
# so we use Playwright to properly evaluate the session.
_SBI_CHECK_URL = "https://site1.sbisec.co.jp/ETGate/?_ControlID=WPLETpfR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETpfR001Control&OutSide=on&getFlg=on&_scpr=intpr=hn_trade"
COOKIE_FILE = Path(__file__).parent / ".cookie"
TOKENS_FILE = Path(__file__).parent / ".tokens.json"
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


def _cookie_objects_from_raw(raw: str) -> list[dict]:
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
    """Returns (status, error_message_or_None)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ("ERROR", "Playwright not installed. Run: pip install playwright && playwright install chromium")

    tokens = parse_cookie_input(cookie_json)
    missing = missing_critical_keys(tokens)
    if missing:
        return ("ERROR", f"Missing critical cookies: {', '.join(missing)}")
    cookie_list = _cookie_objects_from_raw(cookie_json)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800})
            context.add_cookies(cookie_list)
            page = context.new_page()
            page.goto(_SBI_CHECK_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            url = page.url
            html = page.content()
            browser.close()

            status = classify_sbi_html(html, url)
            if status:
                return (status, None)
            return ("ERROR", f"認証状態を判定できません: {url[:120]}")
    except Exception as e:
        return ("ERROR", str(e))


def load_cookie() -> str | None:
    """SBI_COOKIE env var takes precedence, then .tokens.json, then .cookie file."""
    env_val = os.environ.get("SBI_COOKIE", "").strip()
    if env_val:
        return env_val
    if TOKENS_FILE.exists():
        data = json.loads(TOKENS_FILE.read_text())
        tokens = data.get("tokens", data) if isinstance(data, dict) else {}
        if tokens:
            return reconstruct_header(tokens)
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text().strip()
    return None


def cmd_default():
    cookie = load_cookie()
    if not cookie:
        print("STATUS: UNSET")
        print("Cookieが未設定です。")
        print("")
        print("設定手順:")
        print("  1. ブラウザで https://www.sbisec.co.jp/ にログイン")
        print("  2. Cookie-Editorでエクスポート（JSON形式）")
        print("  3. /portfolio-auth にJSONを貼り付けて実行")
        sys.exit(1)

    status, err = validate(cookie)
    print(f"STATUS: {status}")
    if status == "OK":
        print("SBI証券セッションは有効です。")
        # Auto-save valid cookies to persist session
        _save_cookie(cookie)
    elif status == "EXPIRED":
        print("Cookieの有効期限が切れています。ブラウザで再ログインし、/portfolio-auth に新しいCookieを貼り付けてください。")
        sys.exit(1)
    else:
        print(f"検証エラー: {err}")
        sys.exit(1)


def _save_cookie(cookie_str: str):
    """Save cookie to file with restricted permissions."""
    tokens = parse_cookie_input(cookie_str)
    COOKIE_FILE.write_text(cookie_str)
    COOKIE_FILE.chmod(0o600)
    TOKENS_FILE.write_text(json.dumps({"tokens": tokens}, ensure_ascii=False, indent=2))
    TOKENS_FILE.chmod(0o600)
    print(f"Cookieを保存しました: {COOKIE_FILE}")


def cmd_save():
    cookie = os.environ.get("SBI_COOKIE", "").strip()
    if not cookie:
        print("ERROR: SBI_COOKIE 環境変数が未設定です。")
        print("先に export SBI_COOKIE=\"...\" で設定してください。")
        sys.exit(1)
    tokens = parse_cookie_input(cookie)
    missing = missing_critical_keys(tokens)
    if missing:
        print(f"ERROR: 以下の重要トークンが見つかりません: {', '.join(missing)}")
        sys.exit(1)

    status, err = validate(cookie)
    if status != "OK":
        print(f"ERROR: Cookie検証失敗 ({status})")
        if err:
            print(f"  {err}")
        print("SBI_COOKIE の値が正しいか確認してください。")
        sys.exit(1)

    _save_cookie(cookie)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--save":
        cmd_save()
    else:
        cmd_default()
