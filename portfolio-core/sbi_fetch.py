"""SBI portfolio page fetching, HTML parsing, and portfolio merging.

Extracted from Claude版 portfolio-fetch/scripts/fetch_portfolio.py.
Uses Playwright for SBI page access (urllib fallback).
Adopts agent版's margin expiry_date calculation and safer merge guard.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

import yaml

from cookie_store import read_cookie_bundle
from sbi_auth import classify_sbi_html

# SBI URLs — JSESSIONID is hostOnly for site1.sbisec.co.jp.
_SBI_PORTFOLIO_URL = "https://site1.sbisec.co.jp/ETGate/?_ControlID=WPLETpfR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETpfR001Control&OutSide=on&getFlg=on&_scpr=intpr=hn_trade"
_SBI_PORTFOLIO_URL_DESKTOP = "https://site1.sbisec.co.jp/ETGate/?_ControlID=WPLETpfR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETpfR001Control&OutSide=on&getFlg=on&_scpr=intpr=hn_trade"
_SBI_ACCOUNT_URL = "https://site1.sbisec.co.jp/ETGate/?_ControlID=WPLETacR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETacR001Control&OutSide=on&getFlg=on&_scpr=intpr=hn_acc"

_MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
_DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

SBI_TICKER_MAP = {
    "ＮＦ金価格": "1328.T",
    "日鉄鉱": "1515.T",
    "ＯＬＣ": "4661.T",
    "任天堂": "7974.T",
    "ＳＢＩ": "8473.T",
    "ＩＨＩ": "7013.T",
    "ソニーＦＧ": "8729.T",
}


def _sbi_headers(cookie: str, user_agent: str | None = None) -> dict[str, str]:
    return {
        "Cookie": cookie,
        "User-Agent": user_agent or _DESKTOP_UA,
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://site1.sbisec.co.jp/",
    }


def fetch_sbi_page(url: str = None, user_agent: str = None) -> tuple[str | None, str]:
    if url is None:
        url = _SBI_PORTFOLIO_URL

    bundle = read_cookie_bundle()
    cookie_list = bundle["cookie_objects"]
    if not cookie_list:
        print("[AUTH_EXPIRED] No Playwright cookies available from cookie source", file=sys.stderr)
        return (None, "auth_expired")
    print(f"[INFO] SBI Cookie source: {bundle['source']} fingerprint={bundle['fingerprint']} saved_at={bundle.get('saved_at', '-')}", file=sys.stderr)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _fetch_sbi_page_urllib(url, user_agent)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                locale="ja-JP", timezone_id="Asia/Tokyo",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            print(f"[DEBUG] Setting {len(cookie_list)} cookies, JSESSIONID={'...' if any(c['name']=='JSESSIONID' for c in cookie_list) else 'MISSING'}", file=sys.stderr)
            context.add_cookies(cookie_list)
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            current_url = page.url
            if "login" in current_url.lower():
                browser.close()
                return (None, "auth_expired")
            html = page.content()
            browser.close()
            html_status = classify_sbi_html(html, current_url)
            if html_status and html_status != "OK":
                return (None, "auth_expired" if html_status == "EXPIRED" else html_status.lower())
            if len(html) < 5000:
                return (None, "auth_expired")
            return (html, "ok")
    except Exception as e:
        print(f"[WARN] Playwright fetch failed: {e}", file=sys.stderr)
        return (None, "http_error")


def _fetch_sbi_page_urllib(url: str, user_agent: str = None) -> tuple[str | None, str]:
    bundle = read_cookie_bundle()
    cookie = bundle["cookie_header"]
    if not cookie:
        return (None, "auth_expired")
    if user_agent is None:
        user_agent = _MOBILE_UA
    req = urllib.request.Request(url, headers=_sbi_headers(cookie, user_agent))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.getcode() != 200 or len(raw) < 1000:
                return (None, "auth_expired" if len(raw) < 1000 else "http_error")
            for enc in ["cp932", "shift_jis", "utf-8"]:
                try:
                    html = raw.decode(enc)
                    status = classify_sbi_html(html, resp.geturl())
                    return (None, "auth_expired" if status == "EXPIRED" else status.lower()) if status else (html, "ok")
                except UnicodeDecodeError:
                    continue
            html = raw.decode("cp932", errors="replace")
            status = classify_sbi_html(html, resp.geturl())
            return (None, "auth_expired" if status == "EXPIRED" else status.lower()) if status else (html, "ok")
    except Exception as e:
        print(f"[WARN] urllib fetch failed: {e}", file=sys.stderr)
        return (None, "http_error")


def parse_sbi_holdings(html: str) -> tuple[list[dict], dict]:
    holdings = []
    account: dict[str, float] = {}
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)

    m = re.search(r"現金残高等\s+([\d,]+)", text)
    if m: account["available_cash"] = float(m.group(1).replace(",", ""))
    m = re.search(r"建代金合計[（(]B[)）]\s+([\d,]+)", text)
    if m: account["margin_principal"] = float(m.group(1).replace(",", ""))
    m = re.search(r"委託保証金率[（(]A/B[)）][×x]\s*100\s+([\d,.]+)%", text)
    if m: account["margin_ratio"] = float(m.group(1).replace(",", ""))
    m = re.search(r"買付余力[（(]2営業日後[)）]\s+([\d,]+)", text)
    if m: account["buying_power"] = float(m.group(1).replace(",", ""))
    m = re.search(r"実質保証金[（(]A[)）]\s+([\d,]+)", text)
    if m: account["margin_collateral"] = float(m.group(1).replace(",", ""))
    m = re.search(r"保有資産評価[\s\S]*?([\d,]{7,})", text)
    if m: account["total_assets"] = float(m.group(1).replace(",", ""))

    # Spot holdings
    spot_pattern = re.compile(
        r"(\d{3,4}[A-Z]?)\s+(\S+?)\s+[0-9\-/]+\s+([\d,]+)\s+([\d,.]+)\s+([\d,]+)\s+")
    spot_section_pattern = re.compile(r"株式[（(]現物/(?:特定預り|NISA|一般預り)[）)]")
    spot_ranges = [m.start() for m in spot_section_pattern.finditer(html)]
    credit_marker = html.find("株式（信用）")
    if credit_marker < 0: credit_marker = html.find("株式(信用)")
    if credit_marker < 0: credit_marker = html.find("信用建玉")

    for i, start in enumerate(spot_ranges):
        end = spot_ranges[i + 1] if i + 1 < len(spot_ranges) else credit_marker
        if end < 0 or end <= start: end = start + 20000
        section_html = html[start:end]
        section_text = re.sub(r"<[^>]+>", " ", section_html)
        section_text = re.sub(r"&nbsp;", " ", section_text)
        section_text = re.sub(r"\s+", " ", section_text)
        if "NISA（成長投資枠）" in section_html or "NISA(成長投資枠)" in section_html:
            account_type = "NISA成長"
        elif "NISA（つみたて投資枠）" in section_html or "NISA(つみたて投資枠)" in section_html:
            account_type = "NISAつみたて"
        elif "一般預り" in section_html: account_type = "一般"
        else: account_type = "特定"
        for sm in spot_pattern.finditer(section_text):
            ticker = SBI_TICKER_MAP.get(sm.group(2), f"{sm.group(1)}.T")
            holdings.append({
                "ticker": ticker, "name": sm.group(2), "position_type": "現物",
                "account_type": account_type, "quantity": int(float(sm.group(3).replace(",", ""))),
                "cost_price": float(sm.group(4).replace(",", "")),
                "current_price": float(sm.group(5).replace(",", "")),
            })

    # Margin holdings
    if credit_marker > 0:
        credit_end = html.find("投資信託", credit_marker)
        if credit_end < 0: credit_end = len(html)
        credit_html = html[credit_marker:credit_end]
        credit_text = re.sub(r"<[^>]+>", " ", credit_html)
        credit_text = re.sub(r"&nbsp;", " ", credit_text)
        credit_text = re.sub(r"\s+", " ", credit_text)
        margin_pattern = re.compile(
            r"(\d{3,4}[A-Z]?)\s+(\S+?)\s+(?:買建|売建)\s+"
            r"(\S+?)\s+([0-9\-/]+)\s+([\d,]+)\s+([\d,.]+)\s+([\d,]+)")
        for mm in margin_pattern.finditer(credit_text):
            ticker = SBI_TICKER_MAP.get(mm.group(2), f"{mm.group(1)}.T")
            term_str = mm.group(3)
            open_date = mm.group(4)
            qty = int(float(mm.group(5).replace(",", "")))
            cost = float(mm.group(6).replace(",", ""))
            price = float(mm.group(7).replace(",", ""))
            open_date_iso = None
            if open_date and "/" in open_date and not open_date.startswith("--"):
                parts = [p for p in open_date.split("/") if p.strip() and not p.strip().startswith("-")]
                if len(parts) == 3:
                    try:
                        y, m, d = parts
                        y = f"20{y}" if len(y) == 2 else y
                        datetime.strptime(f"{y}-{m}-{d}", "%Y-%m-%d")
                        open_date_iso = f"{y}-{m}-{d}"
                    except ValueError: pass
            expiry_date_iso = None
            if open_date_iso and term_str:
                term_match = re.search(r"(\d+)\s*(ヶ|年|月)", term_str)
                if term_match:
                    term_num = int(term_match.group(1))
                    term_months = term_num * 12 if term_match.group(2) == "年" else term_num
                    try:
                        open_dt = datetime.strptime(open_date_iso, "%Y-%m-%d")
                        exp_year = open_dt.year + (open_dt.month + term_months - 1) // 12
                        exp_month = (open_dt.month + term_months - 1) % 12 + 1
                        exp_day = min(open_dt.day, 28)
                        expiry_date_iso = f"{exp_year:04d}-{exp_month:02d}-{exp_day:02d}"
                    except ValueError: pass
            holdings.append({
                "ticker": ticker, "name": mm.group(2), "position_type": "信用",
                "quantity": qty, "cost_price": cost, "current_price": price,
                "open_date": open_date_iso, "expiry_date": expiry_date_iso,
            })
    return holdings, account


def parse_sbi_account(html: str) -> dict[str, float]:
    account: dict[str, float] = {}
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"現金残高等\s+([\d,]+)\s+株式\s+([\d,]+)", text)
    if m:
        account["available_cash"] = float(m.group(1).replace(",", ""))
        account["stock_value"] = float(m.group(2).replace(",", ""))
    m = re.search(r"計\s+([\d,]{7,})", text)
    if m: account["total_assets"] = float(m.group(1).replace(",", ""))
    m = re.search(r"建代金合計[（(]B[)）]\s+([\d,]+)", text)
    if m: account["margin_principal"] = float(m.group(1).replace(",", ""))
    m = re.search(r"委託保証金率\S*\s+([\d,.]+)\s*[%％]", text)
    if m: account["margin_ratio"] = float(m.group(1).replace(",", ""))
    m = re.search(r"買付余力[（(]2営業日後[)）]\s+([\d,]+)", text)
    if m: account["buying_power"] = float(m.group(1).replace(",", ""))
    m = re.search(r"実質保証金[（(]A[)）]\s+([\d,]+)", text)
    if m: account["margin_collateral"] = float(m.group(1).replace(",", ""))
    return account


def merge_holdings(existing: list, sbi_holdings: list) -> list | None:
    if existing and len(sbi_holdings) < len(existing) * 0.5:
        print(f"[WARN] SBI holdings ({len(sbi_holdings)}) < 50% of existing ({len(existing)}). Merge aborted.", file=sys.stderr)
        return None
    def key_for(h):
        if h.get("position_type") == "信用":
            return (h.get("ticker"), "信用", h.get("open_date"))
        return (h.get("ticker"), h.get("position_type", "現物"), h.get("account_type"))
    existing_index = {key_for(h): h for h in existing}
    merged = []
    for sbi_h in sbi_holdings:
        old = existing_index.get(key_for(sbi_h), {})
        item = dict(old)
        item.update(sbi_h)
        merged.append(item)
    return merged


def sync_from_sbi(portfolio_path: str) -> str:
    bundle = read_cookie_bundle()
    if not bundle["cookie_objects"]:
        return "no_cookie"
    html, fetch_status = fetch_sbi_page()
    if fetch_status in ("auth_expired",):
        print("[AUTH_EXPIRED] Cookie rejected by SBI", file=sys.stderr)
        return "auth_expired"
    if fetch_status == "maintenance":
        print("[INFO] SBIサイトがメンテナンス中です。", file=sys.stderr)
        return "maintenance"
    if html is None:
        return "network_error"
    holdings, _ = parse_sbi_holdings(html)
    html_status = classify_sbi_html(html)
    if html_status and html_status not in ("OK",):
        return "auth_expired" if html_status == "EXPIRED" else html_status.lower()
    if not holdings:
        print("[INFO] Mobile parse returned 0 holdings, retrying with desktop UA...", file=sys.stderr)
        html2, status2 = fetch_sbi_page(url=_SBI_PORTFOLIO_URL_DESKTOP, user_agent=_DESKTOP_UA)
        if status2 == "auth_expired":
            return "auth_expired"
        if html2:
            holdings, _ = parse_sbi_holdings(html2)
            if holdings: html = html2
    if not holdings:
        print("[WARN] SBIから保有銘柄を抽出できませんでした。", file=sys.stderr)
        debug_path = "/tmp/sbi_debug.html"
        try:
            with open(debug_path, "w", encoding="utf-8") as df:
                df.write(html)
            print(f"[DEBUG] SBI HTML saved to {debug_path} ({len(html)} chars)", file=sys.stderr)
        except Exception: pass
        return "parse_error"
    # Account data
    account: dict[str, float] = {}
    try:
        bundle2 = read_cookie_bundle()
        c = bundle2["cookie_header"]
        req = urllib.request.Request(_SBI_ACCOUNT_URL, headers=_sbi_headers(c, _DESKTOP_UA))
        with urllib.request.urlopen(req, timeout=15) as resp:
            acc_html = resp.read().decode("cp932", errors="replace")
        account = parse_sbi_account(acc_html)
    except Exception as e:
        print(f"[WARN] SBI account page fetch failed: {e}", file=sys.stderr)
    # Load existing
    existing = {}
    if os.path.isfile(portfolio_path):
        try:
            with open(portfolio_path, encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {}
        except Exception: pass
    existing_account = existing.get("account", {})
    for key in ("total_assets", "available_cash", "margin_ratio", "buying_power", "margin_principal"):
        val = account.get(key)
        if val is not None: existing_account[key] = val
    existing_holdings = existing.get("holdings", [])
    if existing_holdings:
        merged = merge_holdings(existing_holdings, holdings)
        if merged is None: return "parse_error"
    else:
        merged = holdings
    portfolio = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "last_successful_sync_at": datetime.now(timezone.utc).isoformat(),
        "last_sync_source": "SBI", "sync_status": "ok",
        "account": existing_account, "holdings": merged,
    }
    os.makedirs(os.path.dirname(portfolio_path), exist_ok=True)
    tmp_path = f"{portfolio_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(portfolio, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.replace(tmp_path, portfolio_path)
    return "ok"
