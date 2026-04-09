#!/usr/bin/env python3
"""sbi_sync.py — SBI証券のHTMLを解析してポートフォリオデータを抽出する"""
import sys
import os
import re
import subprocess
from bs4 import BeautifulSoup
import yaml

SBI_BASE = "https://www.sbisec.co.jp/ETGate"

SBI_PAGES = {
    "holdings": "/?_=1&_PageID=DefaultPID&_ControlID=WPLETstT001Control&_SeqNo=1&_PrmNm=&_PrmNm2=&getFlg=on&_MenuID=MENU_WPLETST001&_KessaiFlg=on",
    "account":  "/?_=1&_PageID=DefaultPID&_ControlID=WPLETacR001Control&_SeqNo=1&_PrmNm=&_MenuID=MENU_WPLETAC001",
}

PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio.yaml")


def _clean_number(text: str) -> str:
    """カンマ・円記号を除去して数値文字列にする。"""
    return re.sub(r"[,円]", "", text.strip())


def parse_holdings_html(html: str) -> list[dict]:
    # ログインページにリダイレクトされた場合
    if "ログイン" in html and "tbl01" not in html:
        raise ValueError(
            "SBI証券のCookieが無効です。ブラウザから新しいCookieを取得して "
            "SBI_COOKIE 環境変数に設定してください。"
        )
    soup = BeautifulSoup(html, "lxml")
    results = []
    for table in soup.find_all("table", class_="tbl01"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        col_map = {}
        for i, h in enumerate(headers):
            if h == "銘柄コード":
                col_map["ticker"] = i
            elif h == "銘柄名":
                col_map["name"] = i
            elif h == "保有数量":
                col_map["quantity"] = i
            elif h == "取得単価":
                col_map["cost_price"] = i
        if "ticker" not in col_map:
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < len(col_map):
                continue
            entry = {}
            if "ticker" in col_map:
                entry["ticker"] = cells[col_map["ticker"]].get_text(strip=True)
            if "name" in col_map:
                entry["name"] = cells[col_map["name"]].get_text(strip=True)
            if "quantity" in col_map:
                entry["quantity"] = int(_clean_number(cells[col_map["quantity"]].get_text()))
            if "cost_price" in col_map:
                entry["cost_price"] = int(_clean_number(cells[col_map["cost_price"]].get_text()))
            results.append(entry)
    return results


def parse_account_html(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    total_assets = None
    available_cash = None
    for table in soup.find_all("table", class_="tbl01"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True)
            try:
                value = int(_clean_number(cells[1].get_text(strip=True)))
            except ValueError:
                continue
            if "預り金合計" in label:
                total_assets = value
            elif "買付可能額" in label:
                available_cash = value
    return {"total_assets": total_assets, "available_cash": available_cash}


def fetch_sbi_page(page_key: str, cookie: str) -> str:
    """Jina Reader経由でSBI証券のページHTMLを取得する。"""
    url = SBI_BASE + SBI_PAGES.get(page_key, "")
    jina_url = f"https://r.jina.ai/{url}"
    try:
        result = subprocess.run(
            ["curl", "-s", "-L",
             "-H", f"Cookie: {cookie}",
             "-H", "X-Return-Format: html",
             "--max-time", "30",
             jina_url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr}")
        if len(result.stdout) < 500:
            raise RuntimeError("Response too short — possible auth failure")
        return result.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError("SBI証券への接続がタイムアウトしました")


def sync_to_portfolio(holdings: list[dict], account: dict):
    """解析結果を portfolio.yaml に書き込む。"""
    if os.path.isfile(PORTFOLIO_PATH):
        with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
            portfolio = yaml.safe_load(f) or {}
    else:
        portfolio = {}

    portfolio.setdefault("account", {})
    if account.get("total_assets") is not None:
        portfolio["account"]["total_assets"] = account["total_assets"]
    if account.get("available_cash") is not None:
        portfolio["account"]["available_cash"] = account["available_cash"]

    existing_holdings = portfolio.get("holdings", [])
    existing_map = {}
    for h in existing_holdings:
        key = (h["ticker"], h.get("position_type", "現物"))
        existing_map[key] = h

    new_holdings = []
    for h in holdings:
        key = (h["ticker"], h.get("position_type", "現物"))
        if key in existing_map:
            merged = existing_map[key].copy()
            merged["quantity"] = h["quantity"]
            if "cost_price" in h:
                merged["cost_price"] = h["cost_price"]
            if "name" in h and h["name"]:
                merged["name"] = h["name"]
            new_holdings.append(merged)
        else:
            entry = {
                "ticker": h["ticker"],
                "name": h.get("name", h["ticker"]),
                "quantity": h["quantity"],
                "cost_price": h.get("cost_price", 0),
                "position_type": h.get("position_type", "現物"),
            }
            new_holdings.append(entry)

    portfolio["holdings"] = new_holdings

    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        yaml.dump(portfolio, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"[SBI sync] {len(new_holdings)} 銘柄を portfolio.yaml に反映しました")


def main():
    """スタンドアロン実行: SBI証券からデータを取得してportfolio.yamlを更新する。"""
    cookie = os.environ.get("SBI_COOKIE", "")
    if not cookie:
        print("[SBI sync] SBI_COOKIE が未設定のためスキップします")
        sys.exit(0)

    print("[SBI sync] SBI証券からデータを取得中...")

    try:
        holdings_html = fetch_sbi_page("holdings", cookie)
        holdings = parse_holdings_html(holdings_html)
    except (RuntimeError, ValueError) as e:
        print(f"[SBI sync] 保有一覧の取得に失敗: {e}", file=sys.stderr)
        sys.exit(1)

    if not holdings:
        print("[SBI sync] 保有銘柄が取得できませんでした", file=sys.stderr)
        sys.exit(1)

    try:
        account_html = fetch_sbi_page("account", cookie)
        account = parse_account_html(account_html)
    except (RuntimeError, ValueError) as e:
        print(f"[SBI sync] 口座サマリーの取得に失敗: {e}", file=sys.stderr)
        account = {"total_assets": None, "available_cash": None}

    sync_to_portfolio(holdings, account)
    print("[SBI sync] 同期完了")


if __name__ == "__main__":
    main()
