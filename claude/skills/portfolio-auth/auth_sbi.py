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
import urllib.request
import urllib.error
from pathlib import Path

# Use a page that REQUIRES authentication. www.sbisec.co.jp/ETGate is public
# and always returns 200 even with expired cookies (false positive).
SBI_CHECK_URL = "https://www.sbisec.co.jp/ETGate/?_ControlID=WPLETpfR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETpfR001Control&OutSide=on&getFlg=on"
COOKIE_FILE = Path(__file__).parent / ".cookie"


def _build_cookie_header(raw: str, names: set) -> str:
    """Build a Cookie header string from JSON array or plain string format."""
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            pairs = [f"{c['name']}={c['value']}" for c in data if c["name"] in names]
            return "; ".join(pairs)
        except json.JSONDecodeError:
            pass

    pairs = []
    for pair in raw.split("; "):
        if "=" in pair:
            name = pair.split("=", 1)[0].strip()
            if name in names:
                pairs.append(pair)
    return "; ".join(pairs)


def validate(cookie: str) -> tuple[str, str | None]:
    """Returns (status, error_message_or_None)."""
    essential = {"JSESSIONID", "AWSALB", "AWSALBCORS"}
    slim_cookie = _build_cookie_header(cookie, essential)
    req = urllib.request.Request(SBI_CHECK_URL, headers={"Cookie": slim_cookie})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            url = resp.geturl()
    except urllib.error.HTTPError as e:
        return ("ERROR", f"HTTP {e.code}")
    except Exception as e:
        return ("ERROR", str(e))

    # Any redirect away from the authenticated page means the session is
    # invalid. Unauthenticated urllib requests get bounced to either
    # login.sbisec.co.jp or search.sbisec.co.jp/attention/maintenance.html.
    if url != SBI_CHECK_URL:
        return ("EXPIRED", f"redirected to {url[:80]}")
    return ("OK", None)


def load_cookie() -> str | None:
    """SBI_COOKIE env var takes precedence, then .cookie file."""
    env_val = os.environ.get("SBI_COOKIE", "").strip()
    if env_val:
        return env_val
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
    COOKIE_FILE.write_text(cookie_str)
    COOKIE_FILE.chmod(0o600)
    print(f"Cookieを保存しました: {COOKIE_FILE}")


def cmd_save():
    cookie = os.environ.get("SBI_COOKIE", "").strip()
    if not cookie:
        print("ERROR: SBI_COOKIE 環境変数が未設定です。")
        print("先に export SBI_COOKIE=\"...\" で設定してください。")
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
