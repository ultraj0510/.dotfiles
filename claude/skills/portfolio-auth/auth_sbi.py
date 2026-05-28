#!/usr/bin/env python3
"""SBI証券セッションCookieの管理・検証。

Cookieはユーザがブラウザから手動取得し、--save でファイル保存する。
保存先: ~/.config/sbi-portfolio/tokens.json

Usage:
  python3 auth_sbi.py           # 保存済みCookieの有効性を検証
  python3 auth_sbi.py --save    # SBI_COOKIE環境変数の値を検証→保存
"""

import os
import sys

_CORE = os.path.expanduser("~/.dotfiles/portfolio-core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from cookie_store import read_cookie, save_cookie
from sbi_auth import validate, parse_cookie_input, missing_critical_keys


def cmd_default():
    cookie = read_cookie()
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
        save_cookie(cookie)
        print(f"Cookieを保存しました: ~/.config/sbi-portfolio/tokens.json")
    elif status in ("EXPIRED", "MAINTENANCE"):
        print("Cookieの有効期限が切れています。ブラウザで再ログインし、/portfolio-auth に新しいCookieを貼り付けてください。")
        sys.exit(1)
    else:
        print(f"検証エラー: {err}")
        sys.exit(1)


def cmd_save():
    cookie = os.environ.get("SBI_COOKIE", "").strip()
    if not cookie:
        print("ERROR: SBI_COOKIE 環境変数が未設定です。")
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
        sys.exit(1)

    save_cookie(cookie)
    print(f"Cookieを保存しました: ~/.config/sbi-portfolio/tokens.json")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--save":
        cmd_save()
    else:
        cmd_default()
