#!/usr/bin/env python3
"""SBI証券セッションCookieの管理・検証。

Cookieはユーザがブラウザから手動取得し、--save でファイル保存する。
保存先: ~/.config/sbi-portfolio/tokens.json

Usage:
  python3 auth_sbi.py                  # 保存済みCookieの有効性を検証
  python3 auth_sbi.py --save           # SBI_COOKIE環境変数の値を検証→保存
  python3 auth_sbi.py --save-stdin     # stdinからCookieを読み取り検証→保存
  python3 auth_sbi.py --save-file PATH # ファイルからCookieを読み取り検証→保存
"""

import argparse
import os
import sys
from pathlib import Path

# Auto-discover a venv with Playwright if system python3 lacks it
try:
    from playwright.sync_api import sync_playwright  # noqa: F401
except ImportError:
    candidates = [
        os.path.expanduser("~/.claude/skills/stock-advisor/scripts/.venv/bin/python"),
        os.path.expanduser("~/.agents/skills/portfolio-auth/.venv/bin/python"),
        os.path.expanduser("~/.dotfiles/claude/skills/portfolio-auth/.venv/bin/python"),
    ]
    for venv_python in candidates:
        if os.path.isfile(venv_python) and os.access(venv_python, os.X_OK):
            os.execv(venv_python, [venv_python] + sys.argv)

_CORE = os.path.expanduser("~/.dotfiles/portfolio-core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from cookie_store import read_cookie, save_cookie
from sbi_auth import validate, parse_cookie_input, missing_critical_keys


def parse_args():
    parser = argparse.ArgumentParser(description="Validate and save SBI session Cookie")
    parser.add_argument("--save", action="store_true",
                        help="Read Cookie from SBI_COOKIE env var and save after validation")
    parser.add_argument("--save-stdin", action="store_true",
                        help="Read Cookie from stdin and save after validation")
    parser.add_argument("--save-file",
                        help="Read Cookie from a 0600 file and save after validation")
    parser.add_argument("unexpected", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.unexpected:
        parser.error("Unexpected positional Cookie input. "
                     "Use --save-stdin, --save-file, or SBI_COOKIE with --save.")
    return args


def save_fresh_cookie(cookie: str, source: str):
    tokens = parse_cookie_input(cookie)
    missing = missing_critical_keys(tokens)
    if missing:
        print(f"ERROR: Missing critical cookies: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    status, err = validate(cookie)
    if status != "OK":
        print(f"ERROR: Cookie validation failed ({status})", file=sys.stderr)
        if err:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    save_cookie(cookie, source=source)
    print("STATUS: OK")
    print("Cookie saved: ~/.config/sbi-portfolio/tokens.json")


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
    elif status in ("EXPIRED", "MAINTENANCE"):
        print("Cookieの有効期限が切れています。ブラウザで再ログインし、/portfolio-auth に新しいCookieを貼り付けてください。")
        sys.exit(1)
    else:
        print(f"検証エラー: {err}")
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    if args.save:
        cookie = os.environ.get("SBI_COOKIE", "").strip()
        if not cookie:
            print("ERROR: SBI_COOKIE is unset.", file=sys.stderr)
            sys.exit(1)
        save_fresh_cookie(cookie, source="env")
    elif args.save_stdin:
        cookie = sys.stdin.read().strip()
        if not cookie:
            print("ERROR: stdin Cookie is empty.", file=sys.stderr)
            sys.exit(1)
        save_fresh_cookie(cookie, source="stdin")
    elif args.save_file:
        path = Path(args.save_file)
        if not path.exists():
            print(f"ERROR: Cookie file not found: {args.save_file}", file=sys.stderr)
            sys.exit(1)
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            print("ERROR: Cookie file must be readable only by the owner (0600).", file=sys.stderr)
            sys.exit(1)
        save_fresh_cookie(path.read_text().strip(), source=f"file:{path}")
    else:
        cmd_default()
