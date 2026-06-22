"""Classify IR documents by title and context."""
import re

_HARD_EXCLUDE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"定時株主総会|株主総会招集|招集通知",
        r"定款|変更登記|登記完了",
        r"電子公告|公告",
        r"採用情報|求人|募集",
    ]
]

_SOFT_EXCLUDE_PATTERNS = [
    re.compile(r"プレスリリース|ニュースリリース", re.IGNORECASE),
    re.compile(r"IR(?:イベント|カレンダー|情報)?\s*(?:は|が|の|と|\s|$)", re.IGNORECASE),
]

_INCLUDE_PATTERNS = [
    (re.compile(r"決算短信(?![\s\S]*説明)"), "earnings_release"),
    (re.compile(r"決算説明|決算(?:概要|発表)|financial\s*results?\s*(?:briefing|presentation)"), "earnings_presentation"),
    (re.compile(r"有価証券報告書|有報|四半期報告書|半期報告書|securities\s*report|quarterly\s*report|semi.?annual\s*report"), "securities_report"),
    (re.compile(r"(?:中期|中長期)経営計画|mid.?term\s*(?:management)?\s*plan"), "management_plan"),
    (re.compile(r"業績予想|配当予想|業績修正|forecast|revision"), "forecast_revision"),
    (re.compile(r"月次|マンスリー|monthly|KPI|売上高|営業利益"), "business_kpi"),
    (re.compile(r"適時開示|material\s*disclosure|(?:重要|資本|業務|事業|自己株式|自社株).*(?:お知らせ|開示|取得)"), "material_disclosure"),
    (re.compile(
        r"(?:Investor\s*Day|アナリスト\s*DAY|経営方針説明会).*(?:プレゼンテーション|説明資料|質疑応答)"
        r"|(?:プレゼンテーション|説明資料|質疑応答).*(?:Investor\s*Day|アナリスト\s*DAY|経営方針説明会)",
        re.IGNORECASE,
    ), "other_relevant"),
    (re.compile(r"信用格付|格付.*(?:格上げ|引き上げ|変更)", re.IGNORECASE), "material_disclosure"),
    (re.compile(r"第三者割当|長期供給契約|合弁会社.*契約", re.IGNORECASE), "material_disclosure"),
    (re.compile(r"(?:事業|IR|投資家).*(?:説明|戦略|方針|アップデート)"), "other_relevant"),
]


def classify_document(title, context):
    """Return document category string or None if excluded."""
    combined = f"{title} {context}"

    # Hard exclusions: always reject
    for pattern in _HARD_EXCLUDE_PATTERNS:
        if pattern.search(combined):
            return None

    # Include patterns: first match wins
    for pattern, category in _INCLUDE_PATTERNS:
        if pattern.search(combined):
            return category

    # Soft exclusions: reject only if no include matched
    for pattern in _SOFT_EXCLUDE_PATTERNS:
        if pattern.search(combined):
            return None

    return None
