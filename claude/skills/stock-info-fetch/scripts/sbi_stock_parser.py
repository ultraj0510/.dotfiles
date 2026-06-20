"""SBI Securities stock detail page HTML parsers.

Each section corresponds to a tab on the SBI stock detail page.
Parsers receive HTML strings; they do NOT handle HTTP or cookie reads.
"""
import re
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup

from url_cleaner import clean_url

JST = timezone(timedelta(hours=9))


def ticker_is_valid(code: str) -> bool:
    """Validate a Japanese stock ticker code (4 digits)."""
    return bool(re.fullmatch(r"\d{4}", code))


def _parse_float(s: str) -> float:
    return float(s.replace(",", ""))


def _parse_int(s: str) -> int:
    s = s.replace(",", "").lstrip("+")
    return int(float(s))


def _count_numeric_values(text: str) -> int:
    return len(re.findall(r"[\d,]+\.?\d*", text))


def _within_window(value: datetime, as_of: datetime | None, days: int) -> bool:
    """Check if value is within [as_of-days, as_of] window inclusive.

    Upper bound uses end of as_of day to include items on the same
    calendar day as as_of regardless of time.
    """
    ref = as_of if as_of is not None else datetime.now(JST)
    end_of_day = ref.replace(hour=23, minute=59, second=59)
    return ref - timedelta(days=days) <= value <= end_of_day


def parse_price(html: str, as_of: datetime | None = None) -> dict:
    """Parse SBI price tab HTML into structured data.

    Returns:
        {"status": "ok|not_available|source_changed", "data": {...}}
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Check for "no data" markers before length check
    if "－" in text and _count_numeric_values(text) == 0:
        return {"status": "not_available", "data": {}}

    if not text or len(text) < 10:
        return {"status": "source_changed", "data": {}}

    data = {}
    extracted = 0

    fields = [
        (r"現在値\s*([\d,]+\.?\d*)", "current_price", _parse_float),
        (r"前日比\s*([+-][\d,]+\.?\d*)", "price_change", _parse_float),
        (r"前日比[^)]*?([+-][\d.]+)%", "price_change_percent", _parse_float),
        (r"始値\s*([\d,]+\.?\d*)", "open", _parse_float),
        (r"高値\s*([\d,]+\.?\d*)", "high", _parse_float),
        (r"安値\s*([\d,]+\.?\d*)", "low", _parse_float),
        (r"前日終値\s*([\d,]+\.?\d*)", "previous_close", _parse_float),
        (r"出来高\s*([\d,]+)", "volume", _parse_int),
        (r"売買代金\s*([\d,]+\.?\d*)", "trading_value_million_yen", _parse_float),
        (r"VWAP\s*([\d,]+\.?\d*)", "vwap", _parse_float),
        (r"年初来高値\s*([\d,]+\.?\d*)", "ytd_high", _parse_float),
        (r"年初来安値\s*([\d,]+\.?\d*)", "ytd_low", _parse_float),
        (r"信用売残\s*([\d,]+)", "margin_sell_balance", _parse_int),
        (r"信用売残\s*[\d,]+\s*(?:株)?\s*前週比\s*([+-]?[\d,]+)", "margin_sell_wow_change", _parse_int),
        (r"信用買残\s*([\d,]+)", "margin_buy_balance", _parse_int),
        (r"信用買残\s*[\d,]+\s*(?:株)?\s*前週比\s*([+-]?[\d,]+)", "margin_buy_wow_change", _parse_int),
        (r"貸借倍率\s*([\d,.]+)", "margin_balance_ratio", _parse_float),
        (r"予想PER\s*([\d,.]+)", "forward_per", _parse_float),
        (r"予想EPS\s*([\d,.]+)", "forward_eps", _parse_float),
        (r"実績PBR\s*([\d,.]+)", "trailing_pbr", _parse_float),
        (r"実績BPS\s*([\d,.]+)", "trailing_bps", _parse_float),
        (r"予想配当利回り\s*([\d,.]+)", "forward_dividend_yield", _parse_float),
        (r"予想1株配当\s*([\d,.]+)", "forward_dividend_per_share", _parse_float),
    ]

    for pattern, key, parser in fields:
        m = re.search(pattern, text)
        if m:
            try:
                data[key] = parser(m.group(1))
                extracted += 1
            except ValueError:
                pass

    # Extract quote_timestamp from MM/DD HH:MM pattern
    ts_match = re.search(r"(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", text)
    if ts_match:
        month, day, hour, minute = int(ts_match.group(1)), int(ts_match.group(2)), int(ts_match.group(3)), int(ts_match.group(4))
        ref = as_of or datetime.now(JST)
        for candidate_year in (ref.year, ref.year - 1):
            try:
                dt = datetime(candidate_year, month, day, hour, minute, tzinfo=JST)
                if dt <= ref:
                    data["quote_timestamp"] = dt.isoformat()
                    extracted += 1
                    break
            except ValueError:
                continue

    if extracted == 0:
        return {"status": "source_changed", "data": {}}
    MANDATORY = {"current_price", "quote_timestamp"}
    if not MANDATORY.issubset(data.keys()):
        return {"status": "source_changed", "data": data}
    return {"status": "ok", "data": data}


def _normalize_date(jp_date: str) -> str:
    """Convert '2026年6月15日' to '2026-06-15'."""
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", jp_date)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return jp_date


def _extract_article_blocks(text: str) -> list[str]:
    """Extract article content from 【...】 blocks positioned between 事業構成 and 業種.

    SBI四季報 places two free-form article blocks (labels vary per company) between
    the 事業構成/連結事業 block and the 業種 block. We identify them by position:
    find all 【...】 blocks, locate the ones after 事業構成 and before 業種.
    """
    blocks = re.findall(r"【(.+?)】\s*(.+?)(?=\n?【|\Z)", text, re.DOTALL)
    in_range = False
    articles = []
    for label, content in blocks:
        label = label.strip()
        if label in ("連結事業", "事業構成"):
            in_range = True
            continue
        if label in ("業種",):
            break
        if in_range:
            articles.append(content.strip())
    return articles


def parse_company_profile(html: str) -> dict:
    """Parse SBI 四季報 (company profile) tab HTML.

    Extracts company metadata, characteristics, business breakdown, earnings
    and material notes, sector info. Excludes shareholder/executive/employee
    personal data.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if not text or len(text) < 10:
        return {"status": "source_changed", "data": {}}

    if "四季報情報はありません" in text or "該当する情報はありません" in text:
        return {"status": "not_available", "data": {}}

    data = {}
    extracted = 0

    # Extract all 【...】 blocks by position — labels vary across companies.
    blocks = re.findall(r"【(.+?)】\s*(.+?)(?=【|$)", text, re.DOTALL)
    block_map = {label.strip(): content.strip() for label, content in blocks}

    patterns = [
        (r"\d{4}\s+\(株\)(.+?)\s+［", "company_name", lambda s: s.strip()),
        (r"作成日[：:]\s*(\d{4}年\d{1,2}月\d{1,2}日)", "report_date", _normalize_date),
        (r"【ＵＲＬ】\s*(https?://[^\s]+)", "company_url", lambda s: s.rstrip("/")),
        (r"【決算】\s*(\d{1,2}月)", "fiscal_month", str),
        (r"【設立】\s*([0-9.]+)", "established", str),
        (r"【上場】\s*([0-9.]+)", "listed", str),
        (r"【特色】\s*(.+?)\s*(?:【連結事業】|【事業構成】)", "characteristics", lambda s: s.strip()),
        (r"(?:【連結事業】|【事業構成】)\s*(.+?)\s*【", "business_segments", lambda s: s.strip()),
        (r"【業種】\s*(.+?)\s+時価総額順位", "sector", lambda s: s.strip()),
        (r"時価総額順位\s*([0-9]+/[0-9]+社)", "sector_rank", lambda s: s.strip()),
        (r"【比較会社】\s*(.+?)(?:\s*【|$)", "peer_companies", lambda s: s.strip()),
    ]

    for pattern, key, transform in patterns:
        m = re.search(pattern, text)
        if m:
            val = transform(m.group(1))
            if val:
                data[key] = val
                extracted += 1

    # performance_summary and material_notes: the two 【...】 blocks between
    # 事業構成 and 業種, in document order. Labels vary per company
    # (e.g. 【連続増配】【経営統合】 or 【業績回復】【海外展開】).
    article_blocks = _extract_article_blocks(text)
    if len(article_blocks) >= 1:
        data["performance_summary"] = article_blocks[0]
        extracted += 1
    if len(article_blocks) >= 2:
        data["material_notes"] = article_blocks[1]
        extracted += 1

    if extracted == 0:
        return {"status": "source_changed", "data": {}}
    MANDATORY = {"company_name", "report_date", "characteristics", "business_segments"}
    if not MANDATORY.issubset(data.keys()):
        return {"status": "source_changed", "data": data}
    return {"status": "ok", "data": data}
def parse_news(html: str, as_of: datetime | None = None) -> dict:
    """Parse SBI news tab HTML. Returns up to 90 days of news items.

    Each item: {published_at: ISO8601 JST, category: str, headline: str, url: str}
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if not text or len(text) < 10:
        return {"status": "source_changed", "data": []}

    if "ニュースはありません" in text:
        return {"status": "not_available", "data": []}

    items = []
    recognized = 0

    rows = soup.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        date_text = cells[0].get_text(strip=True)
        category = cells[1].get_text(strip=True) if len(cells) >= 3 else ""
        headline_cell = cells[-1]
        link = headline_cell.find("a")
        headline = link.get_text(strip=True) if link else headline_cell.get_text(strip=True)
        url = link.get("href", "") if link else ""

        try:
            dt = datetime.strptime(date_text, "%Y/%m/%d %H:%M")
            dt_jst = dt.replace(tzinfo=JST)
        except ValueError:
            try:
                dt = datetime.strptime(date_text, "%Y/%m/%d")
                dt_jst = dt.replace(tzinfo=JST)
            except ValueError:
                try:
                    # Use a known leap year as base (2024) to handle 02/29,
                    # then snap to the target year. Both target and previous
                    # year are candidates (Feb 29 only exists in leap years).
                    ref = (as_of or datetime.now(JST))
                    target_year = ref.year
                    dt = datetime.strptime(f"2024/{date_text}", "%Y/%m/%d %H:%M")
                    for candidate_year in range(target_year, target_year - 3, -1):
                        try:
                            dt_jst = dt.replace(year=candidate_year, tzinfo=JST)
                            break
                        except ValueError:
                            continue
                    else:
                        continue  # no valid year within 3-year window
                    # Snap to previous year if still in the future
                    if dt_jst > ref:
                        try:
                            dt_jst = dt_jst.replace(year=dt_jst.year - 1)
                        except ValueError:
                            continue
                except ValueError:
                    continue

        # Exclude dates strictly in the future.
        if dt_jst > (as_of or datetime.now(JST)):
            continue
        if not _within_window(dt_jst, as_of, 90):
            recognized += 1
            continue
        recognized += 1

        if url and not url.startswith("http"):
            url = f"https://site1.sbisec.co.jp{url}" if url.startswith("/") else f"https://site1.sbisec.co.jp/{url}"

        items.append({
            "published_at": dt_jst.isoformat(),
            "category": category,
            "headline": headline,
            "url": clean_url(url),
        })

    if not items:
        return {
            "status": "not_available" if recognized else "source_changed",
            "data": [],
        }
    return {"status": "ok", "data": items}


def parse_disclosures(html: str, as_of: datetime | None = None) -> dict:
    """Parse SBI disclosures (適時開示) tab HTML. Returns up to 1 year of items.

    Each item: {published_at: ISO8601 JST, category: str, title: str, url: str}
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if not text or len(text) < 10:
        return {"status": "source_changed", "data": []}

    if "適時開示はありません" in text or "該当する開示はありません" in text:
        return {"status": "not_available", "data": []}

    items = []
    recognized = 0

    rows = soup.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        date_text = cells[0].get_text(strip=True)
        category = cells[1].get_text(strip=True)
        link = cells[2].find("a")
        title = link.get_text(strip=True) if link else cells[2].get_text(strip=True)
        url = link.get("href", "") if link else ""

        try:
            dt = datetime.strptime(date_text, "%Y/%m/%d %H:%M")
            dt_jst = dt.replace(tzinfo=JST)
        except ValueError:
            try:
                dt = datetime.strptime(date_text, "%Y/%m/%d")
                dt_jst = dt.replace(tzinfo=JST)
            except ValueError:
                continue

        if not _within_window(dt_jst, as_of, 365):
            recognized += 1
            continue
        recognized += 1

        if url and not url.startswith("http"):
            url = f"https://site1.sbisec.co.jp{url}" if url.startswith("/") else f"https://site1.sbisec.co.jp/{url}"

        items.append({
            "published_at": dt_jst.isoformat(),
            "category": category,
            "title": title,
            "url": clean_url(url),
        })

    if not items:
        return {
            "status": "not_available" if recognized else "source_changed",
            "data": [],
        }
    return {"status": "ok", "data": items}


def parse_company_scores(html: str) -> dict:
    """Parse SBI company scores (企業スコア) iframe HTML.

    Returns six scores (1-10 scale): total_score, financial_health,
    profitability, valuation, stability, price_momentum.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if not text or len(text) < 10:
        return {"status": "source_changed", "data": {}}

    if "スコア情報はありません" in text or "対象データがありません" in text:
        return {"status": "not_available", "data": {}}

    data = {}
    extracted = 0

    score_map = [
        (r"企業スコア総合\s*([\d.]+)", "total_score"),
        (r"財務健全性\s*([\d.]+)", "financial_health"),
        (r"収益性\s*([\d.]+)", "profitability"),
        (r"割安性\s*([\d.]+)", "valuation"),
        (r"安定性\s*([\d.]+)", "stability"),
        (r"株価モメンタム\s*([\d.]+)", "price_momentum"),
    ]

    for pattern, key in score_map:
        m = re.search(pattern, text)
        if m:
            try:
                data[key] = float(m.group(1))
                extracted += 1
            except ValueError:
                pass

    if extracted == 0:
        return {"status": "source_changed", "data": data}
    MANDATORY = {"total_score", "financial_health", "profitability", "valuation", "stability", "price_momentum"}
    if not MANDATORY.issubset(data.keys()):
        return {"status": "source_changed", "data": data}
    if not all(1.0 <= v <= 10.0 for v in data.values()):
        return {"status": "source_changed", "data": data}
    return {"status": "ok", "data": data}


def parse_performance(html: str) -> dict:
    """Parse STOCK REPORTS HTML page.

    Extracts quarterly/full-year actuals, company forecast, consensus,
    rating, and target price consensus data.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if not text or len(text) < 10:
        return {"status": "source_changed", "data": {}}

    if "業績情報はありません" in text:
        return {"status": "not_available", "data": {}}

    data = {
        "periods": ["1Q", "2Q", "3Q", "通期"],
        "actual_results": [],
        "company_forecast": [],
        "consensus_forecast": [],
        "rating_distribution": {},
    }
    extracted = 0
    unknown_rows = 0

    def parse_value(cell: str) -> dict:
        match = re.search(r"(-?[\d,]+)(?:\s*\(([-\d.]+)%\))?", cell)
        return {
            "value": _parse_float(match.group(1)) if match else None,
            "progress_pct": float(match.group(2)) if match and match.group(2) and re.match(r"-?\d+(\.\d+)?$", match.group(2)) else None,
        }

    def _row_has_any_value(item: dict, periods: list[str]) -> bool:
        return any(
            v.get("value") is not None
            for v in item.get("values", {}).values()
        )

    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        if len(cells) == 5 and re.match(r"\d{4}/\d{2}", cells[0]):
            fiscal_period = cells[0].split()[0]
            item = {
                "fiscal_period": fiscal_period,
                "values": dict(zip(data["periods"], map(parse_value, cells[1:]))),
            }
            if not _row_has_any_value(item, data["periods"]):
                continue
            if "コンセンサス予想" in cells[0]:
                data["consensus_forecast"].append(item)
                extracted += 1
            elif "会社予想" in cells[0] and "会社実績" not in cells[0]:
                data["company_forecast"].append(item)
                extracted += 1
            elif "会社実績" in cells[0]:
                data["actual_results"].append(item)
                extracted += 1
            else:
                unknown_rows += 1

    # Rating current value
    rating_table = soup.find(
        lambda tag: tag.name == "table"
        and "1週間前" in tag.get_text()
        and "3ヶ月前" in tag.get_text(),
    )
    if rating_table:
        cells = [c.get_text(strip=True) for c in rating_table.find_all("td")]
        if cells:
            try:
                data["rating_current"] = float(cells[0])
                extracted += 1
            except ValueError:
                pass

    # Rating distribution
    labels = {"強気": "strong", "やや強気": "moderately_strong",
              "中立": "neutral", "やや弱気": "moderately_weak", "弱気": "weak"}
    dist_extracted = 0
    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        if len(cells) >= 2:
            for label, key in labels.items():
                if cells[0].startswith(label):
                    count = re.search(r"(\d+)人", cells[1])
                    if count:
                        data["rating_distribution"][key] = int(count.group(1))
                    dist_extracted += 1

    # Target price
    target = re.search(
        r"最新値\s*対前週変化率\s*かい離率\s*([\d,]+)円\s*([+-]?[\d.]+)%\s*([+-]?[\d.]+)%",
        text,
    )
    if target:
        data["target_price_consensus"] = _parse_float(target.group(1))
        data["target_price_wow_change_pct"] = float(target.group(2))
        data["target_price_vs_market_pct"] = float(target.group(3))
        extracted += 1

    if extracted == 0 and unknown_rows == 0:
        return {"status": "source_changed", "data": data}  # preserve dist/target if any
    if unknown_rows > 0:
        return {"status": "source_changed", "data": data}
    return {"status": "ok", "data": data}
