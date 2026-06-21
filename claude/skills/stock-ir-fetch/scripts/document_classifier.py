"""Classify IR documents by title and context."""
import re

_EXCLUDE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"定時株主総会|株主総会招集|招集通知",
        r"定款|変更登記|登記完了",
        r"電子公告|公告",
        r"採用情報|求人|募集",
        r"プレスリリース|ニュースリリース",
        r"IR(?:イベント|カレンダー|情報)?\s*(?:は|が|の|と|\s|$)",
    ]
]

_INCLUDE_PATTERNS = [
    (re.compile(r"決算短信(?![\s\S]*説明)"), "earnings_release"),
    (re.compile(r"決算説明|決算(?:概要|発表)|financial\s*results?\s*(?:briefing|presentation)"), "earnings_presentation"),
    (re.compile(r"有価証券報告書|有報|securities\s*report"), "securities_report"),
    (re.compile(r"四半期報告書|半期報告書|quarterly\s*report|semi.?annual\s*report"), "quarterly_report"),
    (re.compile(r"(?:中期|中長期)経営計画|mid.?term\s*(?:management)?\s*plan"), "management_plan"),
    (re.compile(r"業績予想|配当予想|業績修正|forecast|revision"), "forecast_revision"),
    (re.compile(r"月次|マンスリー|monthly|KPI|売上高|営業利益"), "business_kpi"),
    (re.compile(r"適時開示|material\s*disclosure|(?:重要|資本|業務|事業).*(?:お知らせ|開示)"), "material_disclosure"),
    (re.compile(r"(?:自己株式|自社株)取得"), "treasury_stock"),
    (re.compile(r"(?:事業|IR|投資家).*(?:説明|戦略|方針|アップデート)"), "other_relevant"),
]


def classify_document(title, context):
    """Return document category string or None if excluded."""
    combined = f"{title} {context}"
    for pattern in _EXCLUDE_PATTERNS:
        if pattern.search(combined):
            return None
    for pattern, category in _INCLUDE_PATTERNS:
        if pattern.search(combined):
            return category
    return None
