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


@pytest.mark.parametrize(
    ("title", "context", "expected"),
    [
        (
            "プレゼンテーション資料（スクリプト付き）",
            "Investor Day（2026年6月2日）",
            "other_relevant",
        ),
        (
            "質疑応答集",
            "経営方針説明会（2026年6月2日）",
            "other_relevant",
        ),
        (
            "S&Pとフィッチによる信用格付がBBB-へ格上げ",
            "",
            "material_disclosure",
        ),
        (
            "Nanya Technology Corporationの第三者割当増資引受及びDRAM長期供給契約締結に関するお知らせ",
            "",
            "material_disclosure",
        ),
    ],
)
def test_classifies_current_strategy_and_material_documents(title, context, expected):
    assert classify_document(title, context) == expected


def test_generic_news_release_remains_excluded():
    assert classify_document("新製品ニュースリリース", "") is None


def test_soft_exclusion_does_not_block_include_match():
    """Soft exclusions (press release) must not override hard include matches."""
    assert classify_document("第三者割当増資に関するプレスリリース", "") == "material_disclosure"
