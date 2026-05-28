#!/usr/bin/env python3
"""SBI証券セッションCookieの管理・検証。

Cookieはユーザがブラウザから手動取得し、--save でファイル保存する。
保存先: ~/.claude/skills/portfolio-auth/.cookie

Usage:
  python3 auth_sbi.py           # 保存済みCookieの有効性を検証
  python3 auth_sbi.py --save    # SBI_COOKIE環境変数の値を検証→保存
"""

import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

SBI_CHECK_URL = "https://www.sbisec.co.jp/ETGate"
COOKIE_FILE = Path(__file__).parent / ".cookie"


def validate(cookie: str) -> tuple[str, str | None]:
    """Returns (status, error_message_or_None)."""
    # Only send essential cookies to avoid HTTP 400 from oversized header
    essential = {"JSESSIONID", "AWSALB", "AWSALBCORS"}
    pairs = []
    for pair in cookie.split("; "):
        if "=" in pair:
            name = pair.split("=", 1)[0].strip()
            if name in essential:
                pairs.append(pair)
    slim_cookie = "; ".join(pairs) if pairs else cookie
    req = urllib.request.Request(SBI_CHECK_URL, headers={"Cookie": slim_cookie})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            url = resp.geturl()
    except urllib.error.HTTPError as e:
        return ("ERROR", f"HTTP {e.code}")
    except Exception as e:
        return ("ERROR", str(e))

    if "login" in url.lower() or "/ETGate/login" in url:
        return ("EXPIRED", None)
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
        print("  2. 開発ツール → ストレージ → Cookie から主要Cookieをコピー")
        print("  3. export SBI_COOKIE=\"JSESSIONID=...; AWSALB=...; ...\"")
        print(f"  4. python3 {__file__} --save")
        sys.exit(1)

    status, err = validate(cookie)
    print(f"STATUS: {status}")
    if status == "OK":
        print("SBI証券セッションは有効です。")
    elif status == "EXPIRED":
        print("Cookieの有効期限が切れています。ブラウザで再ログインし、上記手順3-4で再設定してください。")
        sys.exit(1)
    else:
        print(f"検証エラー: {err}")
        sys.exit(1)


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

    COOKIE_FILE.write_text(cookie)
    COOKIE_FILE.chmod(0o600)
    print("OK: Cookieを保存しました。")
    print(f"保存先: {COOKIE_FILE}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--save":
        cmd_save()
    else:
        cmd_default()
