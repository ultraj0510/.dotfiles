"""Tests for STOCK REPORTS PDF parser."""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_parser import parse_stock_report_pdf


@pytest.mark.skipif(importlib.util.find_spec("reportlab") is None,
                    reason="reportlab not installed")
def _make_minimal_pdf(path: Path):
    """Generate a minimal PDF with Japanese text for testing."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas

    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    canvas = Canvas(str(path))
    canvas.setFont("HeiseiKakuGo-W5", 10)
    lines = [
        "更新日: 2026年6月15日",
        "企業概要: ゲーム開発・運営を主力とするIT企業",
        "売上高: 50,000百万円 (2026年3月期)",
        "営業利益: 12,500百万円 (2026年3月期)",
        "PER: 15.2倍",
        "PBR: 1.85倍",
        "業績変化: 新作ヒットにより上方修正",
        "リスク: 為替変動、競争激化",
    ]
    for index, line in enumerate(lines):
        canvas.drawString(40, 800 - index * 20, line)
    canvas.save()


def test_parse_stock_report_pdf_basic(tmp_path):
    if importlib.util.find_spec("reportlab") is None:
        pytest.skip("reportlab not installed")
    pdf_path = tmp_path / "test_report.pdf"
    _make_minimal_pdf(pdf_path)

    result = parse_stock_report_pdf(str(pdf_path))
    assert result["status"] == "ok"
    data = result["data"]
    assert "2026-06-15" in data.get("report_date", "")
    assert "ゲーム開発" in data.get("company_overview", "")
    assert data["key_metrics"].get("per", {}).get("value") == 15.2
    assert "上方修正" in data.get("changes", "")
    assert "為替" in data.get("risk_factors", "")


def test_parse_stock_report_pdf_not_found():
    result = parse_stock_report_pdf("/nonexistent/path.pdf")
    assert result["status"] == "error"


def test_parse_stock_report_pdf_corrupted(tmp_path):
    pdf_path = tmp_path / "corrupted.pdf"
    pdf_path.write_text("not a real PDF file")
    result = parse_stock_report_pdf(str(pdf_path))
    assert result["status"] in ("error", "pdf_parse_failed")


def test_parse_stock_report_pdf_insufficient_data(tmp_path):
    if importlib.util.find_spec("reportlab") is None:
        pytest.skip("reportlab not installed")
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas

    pdf_path = tmp_path / "barely_structured.pdf"
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    canvas = Canvas(str(pdf_path))
    canvas.setFont("HeiseiKakuGo-W5", 10)
    # Only one meaningful data category — below minimum threshold of 2
    canvas.drawString(40, 800, "企業概要: ゲーム開発企業です。")
    canvas.drawString(40, 780, "これは投資レポートとは無関係な文章です。")
    canvas.drawString(40, 760, "ダミーテキストが続きます。")
    canvas.save()

    result = parse_stock_report_pdf(str(pdf_path))
    assert result["status"] == "source_changed"


def test_extract_key_metrics_uses_table_data():
    """When text has no metric patterns, table data must be used."""
    from pdf_parser import _extract_key_metrics
    tables = [["指標", "値", "単位"], ["PER", "15.2", "倍"], ["PBR", "1.85", "倍"]]
    result = _extract_key_metrics("no regex matches here", tables)
    assert result["per"]["value"] == 15.2
    assert result["pbr"]["value"] == 1.85


def test_extracts_periodized_performance_from_tables():
    from pdf_parser import _extract_performance_data
    tables = [
        ["", "2026/03 実績", "2027/03 予想"],
        ["売上高", "100,000", "120,000"],
        ["営業利益", "10,000", "12,500"],
        ["", "百万円", "百万円"],
    ]
    result = _extract_performance_data("", tables)
    assert len(result["actual"]) == 2
    assert result["actual"][0] == {"metric": "売上高", "period": "2026/03", "value": 100000.0, "unit": "百万円"}
    assert result["forecast"][1]["period"] == "2027/03"


@pytest.mark.parametrize(("tables", "expected"), [
    ([["PER", "15.2倍"]], {"value": 15.2, "unit": "倍"}),
    ([["PER\n（予想）", "15.2\n倍"]], {"value": 15.2, "unit": "倍"}),
])
def test_metric_value_and_unit_can_share_cell(tables, expected):
    from pdf_parser import _extract_key_metrics
    assert _extract_key_metrics("", tables)["per"] == expected


def test_split_period_and_kind_headers_are_combined():
    from pdf_parser import _extract_performance_data
    tables = [
        ["", "2026/03", "2027/03"],
        ["", "実績", "予想"],
        ["売上高", "100,000", "120,000"],
        ["単位", "百万円", "百万円"],
    ]
    result = _extract_performance_data("", tables)
    assert result["actual"][0] == {
        "metric": "売上高",
        "period": "2026/03",
        "value": 100000.0,
        "unit": "百万円",
    }
    assert result["forecast"][0]["period"] == "2027/03"


def test_text_fallback_uses_complete_schema():
    from pdf_parser import _extract_performance_data
    result = _extract_performance_data(
        "売上高 100000 120000",
        [],
    )
    # Fallback may have empty period/unit since text has no structured headers
    assert "metric" in result["actual"][0]
    assert "period" in result["actual"][0]
    assert "value" in result["actual"][0]
    assert "unit" in result["actual"][0]
