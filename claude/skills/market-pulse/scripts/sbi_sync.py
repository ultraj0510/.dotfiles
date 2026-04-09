#!/usr/bin/env python3
"""sbi_sync.py — SBI証券のHTMLを解析してポートフォリオデータを抽出する"""
import sys
import os
import re
from bs4 import BeautifulSoup

SBI_BASE = "https://www.sbisec.co.jp/ETGate"


def _clean_number(text: str) -> str:
    """カンマ・円記号を除去して数値文字列にする。"""
    return re.sub(r"[,円]", "", text.strip())


def parse_holdings_html(html: str) -> list[dict]:
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
            value = int(_clean_number(cells[1].get_text()))
            if "預り金合計" in label:
                total_assets = value
            elif "買付可能額" in label:
                available_cash = value
    return {"total_assets": total_assets, "available_cash": available_cash}
