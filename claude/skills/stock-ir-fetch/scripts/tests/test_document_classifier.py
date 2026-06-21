import pytest

from document_classifier import classify_document


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("2026年3月期 決算短信", "earnings_release"),
        ("2026年3月期 決算説明資料", "earnings_presentation"),
        ("有価証券報告書", "securities_report"),
        ("半期報告書", "securities_report"),
        ("第2四半期報告書", "securities_report"),
        ("四半期報告書", "securities_report"),
        ("中期経営計画2028", "management_plan"),
        ("業績予想及び配当予想の修正", "forecast_revision"),
        ("5月度 月次KPI", "business_kpi"),
        ("資本業務提携に関するお知らせ", "material_disclosure"),
        ("自己株式取得に関するお知らせ", "material_disclosure"),
        ("事業戦略説明資料", "other_relevant"),
    ],
)
def test_classification(title, expected):
    assert classify_document(title, "") == expected


@pytest.mark.parametrize(
    "title",
    [
        "定時株主総会招集通知",
        "定款の一部変更に関するお知らせ",
        "電子公告",
        "採用情報",
    ],
)
def test_exclusions(title):
    assert classify_document(title, "IRライブラリー") is None


def test_other_relevant_requires_business_context():
    assert classify_document("事業戦略説明資料", "IRライブラリー") == "other_relevant"
    assert classify_document("お知らせ", "IRライブラリー") is None


def test_navigation_not_classified():
    """Navigation links like IRライブラリー must not be classified."""
    assert classify_document("IRライブラリー", "") is None
